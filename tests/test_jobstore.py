"""Tests for ZeroDBJobStore."""

import base64
import pickle
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.job import Job
from apscheduler.jobstores.base import ConflictingIdError, JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.util import datetime_to_utc_timestamp, utc_timestamp_to_datetime

from zerodb_apscheduler.jobstore import ZeroDBJobStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_func():
    """Dummy function for job creation."""
    return 42


def _make_mock_response(rows=None, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"rows": rows or []}
    resp.raise_for_status = MagicMock()
    return resp


def _make_serialized_state(job_id="test-job-1", next_run_time=None):
    """Create a base64-encoded pickle state that the store can deserialize.

    We build a minimal job state dict compatible with APScheduler's
    Job.__setstate__ format.
    """
    if next_run_time is None:
        next_run_time = datetime(2026, 7, 1, 6, 0, 0, tzinfo=timezone.utc)

    state = {
        "version": 1,
        "id": job_id,
        "func": "tests.test_jobstore:_sample_func",
        "trigger": None,
        "executor": "default",
        "args": (),
        "kwargs": {},
        "name": "_sample_func",
        "misfire_grace_time": 1,
        "coalesce": False,
        "max_instances": 1,
        "next_run_time": next_run_time,
    }
    return base64.b64encode(
        pickle.dumps(state, pickle.HIGHEST_PROTOCOL)
    ).decode("ascii")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestZeroDBJobStoreInit:

    def test_default_table_name(self):
        store = ZeroDBJobStore(api_key="k", project_id="p")
        assert store._table_name == "apscheduler_jobs"

    def test_custom_table_name(self):
        store = ZeroDBJobStore(api_key="k", project_id="p", table_name="my_jobs")
        assert store._table_name == "my_jobs"

    def test_custom_pickle_protocol(self):
        store = ZeroDBJobStore(api_key="k", project_id="p", pickle_protocol=2)
        assert store._pickle_protocol == 2


class TestCredentialResolution:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials")
    def test_explicit_credentials(self, mock_resolve, mock_requests):
        mock_resolve.return_value = ("key", "proj", "https://api.ainative.studio")
        store = ZeroDBJobStore(api_key="key", project_id="proj")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")
        mock_resolve.assert_called_once_with("key", "proj")

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials")
    def test_auto_provision(self, mock_resolve, mock_requests):
        mock_resolve.return_value = ("auto-key", "auto-proj", "https://api.ainative.studio")
        store = ZeroDBJobStore()
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")
        mock_resolve.assert_called_once_with(None, None)
        assert store._api_key == "auto-key"
        assert store._project_id == "auto-proj"


class TestAddJob:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_add_job_success(self, mock_resolve, mock_requests):
        # First call (ensure_table) returns ok, second (get_row) returns empty
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        # Deserialize a mock job to get a Job object
        state_b64 = _make_serialized_state("new-job")
        job = store._reconstitute_job(state_b64)

        store.add_job(job)
        # insert_row should have been called (at least 1 post for table, 1 for query, 1 for insert)
        assert mock_requests.post.call_count >= 2

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_add_duplicate_raises_conflict(self, mock_resolve, mock_requests):
        # get_row returns an existing row
        mock_requests.post.return_value = _make_mock_response(
            [{"job_id": "dup-job", "job_state": "abc"}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        state_b64 = _make_serialized_state("dup-job")
        job = store._reconstitute_job(state_b64)

        with pytest.raises(ConflictingIdError):
            store.add_job(job)


class TestLookupJob:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_lookup_existing_job(self, mock_resolve, mock_requests):
        state_b64 = _make_serialized_state("lookup-job")
        mock_requests.post.return_value = _make_mock_response(
            [{"job_id": "lookup-job", "job_state": state_b64}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        result = store.lookup_job("lookup-job")
        assert result is not None
        assert result.id == "lookup-job"

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_lookup_missing_job(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        result = store.lookup_job("nonexistent")
        assert result is None


class TestRemoveJob:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_remove_existing_job(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response(
            [{"job_id": "j1", "job_state": "x"}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        store.remove_job("j1")
        mock_requests.request.assert_called()

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_remove_missing_raises_lookup_error(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        with pytest.raises(JobLookupError):
            store.remove_job("nonexistent")


class TestUpdateJob:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_update_existing_job(self, mock_resolve, mock_requests):
        state_b64 = _make_serialized_state("upd-job")
        mock_requests.post.return_value = _make_mock_response(
            [{"job_id": "upd-job", "job_state": state_b64}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        job = store._reconstitute_job(state_b64)
        store.update_job(job)  # Should not raise

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_update_missing_raises_lookup_error(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        state_b64 = _make_serialized_state("missing-job")
        job = store._reconstitute_job(state_b64)

        with pytest.raises(JobLookupError):
            store.update_job(job)


class TestGetDueJobs:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_due_jobs(self, mock_resolve, mock_requests):
        nrt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=timezone.utc)
        ts = datetime_to_utc_timestamp(nrt)
        state_b64 = _make_serialized_state("due-job", next_run_time=nrt)

        mock_requests.post.return_value = _make_mock_response(
            [{"job_id": "due-job", "next_run_time": ts, "job_state": state_b64}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        now = datetime(2026, 7, 2, 0, 0, 0, tzinfo=timezone.utc)
        due = store.get_due_jobs(now)
        assert len(due) == 1
        assert due[0].id == "due-job"

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_empty_when_none_due(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert store.get_due_jobs(now) == []


class TestGetNextRunTime:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_next_run_time(self, mock_resolve, mock_requests):
        ts = datetime_to_utc_timestamp(datetime(2026, 7, 1, 6, 0, 0, tzinfo=timezone.utc))
        mock_requests.post.return_value = _make_mock_response(
            [{"next_run_time": ts}]
        )

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        nrt = store.get_next_run_time()
        assert nrt is not None

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_none_when_empty(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        assert store.get_next_run_time() is None


class TestGetAllJobs:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_all_jobs(self, mock_resolve, mock_requests):
        s1 = _make_serialized_state("j1")
        s2 = _make_serialized_state("j2")
        mock_requests.post.return_value = _make_mock_response([
            {"job_id": "j1", "job_state": s1},
            {"job_id": "j2", "job_state": s2},
        ])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        jobs = store.get_all_jobs()
        assert len(jobs) == 2

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_returns_empty_list(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        assert store.get_all_jobs() == []


class TestSerialization:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_roundtrip_serialization(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        state_b64 = _make_serialized_state("rt-job")
        job = store._reconstitute_job(state_b64)
        assert job.id == "rt-job"

        # Re-serialize
        serialized = store._serialize_job(job)
        restored = store._reconstitute_job(serialized)
        assert restored.id == "rt-job"
        assert restored.next_run_time == job.next_run_time


class TestRemoveAllJobs:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_remove_all_jobs(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([
            {"job_id": "j1"}, {"job_id": "j2"},
        ])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")

        store.remove_all_jobs()
        # Should have called delete for each job
        assert mock_requests.request.call_count >= 2


class TestShutdown:

    @patch("zerodb_apscheduler.jobstore.requests")
    @patch("zerodb_apscheduler.jobstore.resolve_credentials",
           return_value=("k", "p", "https://api.ainative.studio"))
    def test_shutdown_is_noop(self, mock_resolve, mock_requests):
        mock_requests.post.return_value = _make_mock_response([])

        store = ZeroDBJobStore(api_key="k", project_id="p")
        scheduler = BackgroundScheduler()
        store.start(scheduler, "zerodb")
        store.shutdown()  # Should not raise
