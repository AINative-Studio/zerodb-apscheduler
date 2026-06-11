"""
ZeroDB-backed job store for APScheduler.

Stores serialized job state in a ZeroDB NoSQL table (``apscheduler_jobs``).
Jobs are queried by ``next_run_time`` for efficient due-job retrieval.
"""

import base64
import pickle

import requests
from apscheduler.job import Job
from apscheduler.jobstores.base import BaseJobStore, ConflictingIdError, JobLookupError
from apscheduler.util import datetime_to_utc_timestamp, utc_timestamp_to_datetime

from zerodb_apscheduler.provision import resolve_credentials

TABLE_NAME = "apscheduler_jobs"


class ZeroDBJobStore(BaseJobStore):
    """APScheduler job store that persists jobs to ZeroDB.

    Usage::

        from apscheduler.schedulers.background import BackgroundScheduler
        from zerodb_apscheduler import ZeroDBJobStore

        scheduler = BackgroundScheduler()
        scheduler.add_jobstore(ZeroDBJobStore())
        scheduler.add_job(my_func, 'cron', hour=6)
        scheduler.start()

    Credentials are resolved automatically:
    1. Constructor args (``api_key``, ``project_id``)
    2. Environment variables (``ZERODB_API_KEY``, ``ZERODB_PROJECT_ID``)
    3. Config file (``~/.zerodb/config.json``)
    4. Auto-provision (free, no signup)

    :param str api_key: ZeroDB API key (optional, auto-resolved)
    :param str project_id: ZeroDB project ID (optional, auto-resolved)
    :param str table_name: name of the ZeroDB table to store jobs in
    :param int pickle_protocol: pickle protocol level for serialization
    """

    def __init__(
        self,
        api_key=None,
        project_id=None,
        table_name=TABLE_NAME,
        pickle_protocol=pickle.HIGHEST_PROTOCOL,
    ):
        super().__init__()
        self._api_key = api_key
        self._project_id = project_id
        self._table_name = table_name
        self._pickle_protocol = pickle_protocol
        self._base_url = None
        self._table_created = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, scheduler, alias):
        super().start(scheduler, alias)
        self._api_key, self._project_id, self._base_url = resolve_credentials(
            self._api_key, self._project_id
        )
        self._ensure_table()

    def shutdown(self):
        pass  # Nothing to release

    # ------------------------------------------------------------------
    # BaseJobStore interface
    # ------------------------------------------------------------------

    def lookup_job(self, job_id):
        row = self._get_row(job_id)
        if row is None:
            return None
        return self._reconstitute_job(row["job_state"])

    def get_due_jobs(self, now):
        timestamp = datetime_to_utc_timestamp(now)
        rows = self._query_rows(
            filters={"next_run_time__lte": timestamp},
            order_by="next_run_time",
        )
        return [self._reconstitute_job(r["job_state"]) for r in rows if r.get("next_run_time") is not None]

    def get_next_run_time(self):
        rows = self._query_rows(
            filters={"next_run_time__ne": None},
            order_by="next_run_time",
            limit=1,
        )
        if not rows:
            return None
        ts = rows[0].get("next_run_time")
        if ts is None:
            return None
        return utc_timestamp_to_datetime(ts)

    def get_all_jobs(self):
        rows = self._query_rows(order_by="next_run_time")
        jobs = []
        failed_ids = []
        for row in rows:
            try:
                jobs.append(self._reconstitute_job(row["job_state"]))
            except Exception:
                self._logger.exception(
                    "Unable to restore job %s -- removing it", row.get("job_id")
                )
                failed_ids.append(row.get("job_id"))

        for job_id in failed_ids:
            self._delete_row(job_id)

        self._fix_paused_jobs_sorting(jobs)
        return jobs

    def add_job(self, job):
        # Check for conflicts
        if self._get_row(job.id) is not None:
            raise ConflictingIdError(job.id)

        self._insert_row(job)

    def update_job(self, job):
        if self._get_row(job.id) is None:
            raise JobLookupError(job.id)

        self._upsert_row(job)

    def remove_job(self, job_id):
        if self._get_row(job_id) is None:
            raise JobLookupError(job_id)

        self._delete_row(job_id)

    def remove_all_jobs(self):
        rows = self._query_rows()
        for row in rows:
            job_id = row.get("job_id")
            if job_id:
                self._delete_row(job_id)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _serialize_job(self, job):
        """Serialize a Job to a base64-encoded pickle string."""
        job_state = job.__getstate__()
        return base64.b64encode(
            pickle.dumps(job_state, self._pickle_protocol)
        ).decode("ascii")

    def _reconstitute_job(self, job_state_b64):
        """Deserialize a Job from a base64-encoded pickle string."""
        job_state = pickle.loads(base64.b64decode(job_state_b64))
        job = Job.__new__(Job)
        job.__setstate__(job_state)
        job._scheduler = self._scheduler
        job._jobstore_alias = self._alias
        return job

    # ------------------------------------------------------------------
    # ZeroDB HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Project-ID": self._project_id,
        }

    def _url(self, path):
        return f"{self._base_url}/api/v1/public/tables/{self._project_id}/{self._table_name}{path}"

    def _ensure_table(self):
        """Create the jobs table if it doesn't exist."""
        if self._table_created:
            return
        try:
            requests.post(
                f"{self._base_url}/api/v1/public/tables/{self._project_id}",
                json={"name": self._table_name},
                headers=self._headers(),
                timeout=15,
            )
        except Exception:
            pass  # Table may already exist
        self._table_created = True

    def _insert_row(self, job):
        timestamp = datetime_to_utc_timestamp(job.next_run_time)
        requests.post(
            self._url("/rows"),
            json={
                "rows": [
                    {
                        "job_id": job.id,
                        "next_run_time": timestamp,
                        "job_state": self._serialize_job(job),
                    }
                ]
            },
            headers=self._headers(),
            timeout=15,
        ).raise_for_status()

    def _upsert_row(self, job):
        timestamp = datetime_to_utc_timestamp(job.next_run_time)
        # Delete old row, insert new
        self._delete_row(job.id)
        self._insert_row(job)

    def _get_row(self, job_id):
        resp = requests.post(
            self._url("/query"),
            json={"filters": {"job_id": job_id}, "limit": 1},
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        rows = data.get("rows") or data.get("data") or []
        return rows[0] if rows else None

    def _query_rows(self, filters=None, order_by=None, limit=None):
        body = {}
        if filters:
            body["filters"] = filters
        if order_by:
            body["order_by"] = order_by
        if limit:
            body["limit"] = limit

        resp = requests.post(
            self._url("/query"),
            json=body,
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("rows") or data.get("data") or []

    def _delete_row(self, job_id):
        requests.request(
            "DELETE",
            self._url("/rows"),
            json={"filters": {"job_id": job_id}},
            headers=self._headers(),
            timeout=15,
        )
