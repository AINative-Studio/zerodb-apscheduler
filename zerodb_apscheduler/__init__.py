"""
zerodb-apscheduler -- APScheduler job store backed by ZeroDB.

Persistent job scheduling with auto-provisioning. No Redis, no database setup.

    from apscheduler.schedulers.background import BackgroundScheduler
    from zerodb_apscheduler import ZeroDBJobStore

    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(ZeroDBJobStore())  # auto-provisions ZeroDB
    scheduler.add_job(my_func, 'cron', hour=6)
    scheduler.start()
"""

from zerodb_apscheduler.jobstore import ZeroDBJobStore  # noqa: F401

__version__ = "0.1.0"
__all__ = ["ZeroDBJobStore"]
