# zerodb-apscheduler

**APScheduler job store backed by ZeroDB.** Persistent job scheduling with auto-provisioning -- no Redis, no database setup.

[![PyPI](https://img.shields.io/pypi/v/zerodb-apscheduler)](https://pypi.org/project/zerodb-apscheduler/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why zerodb-apscheduler?

| | SQLAlchemyJobStore | RedisJobStore | ZeroDBJobStore |
|---|---|---|---|
| **Setup** | Requires a database | Requires Redis | Zero setup |
| **Persistence** | Yes | Yes | Yes (cloud) |
| **Auto-provisioning** | No | No | Yes (free, no signup) |
| **Infrastructure** | Self-managed | Self-managed | Managed |

## Installation

```bash
pip install zerodb-apscheduler
```

## Quick Start

```python
from apscheduler.schedulers.background import BackgroundScheduler
from zerodb_apscheduler import ZeroDBJobStore

def daily_report():
    print("Generating daily report...")

scheduler = BackgroundScheduler()
scheduler.add_jobstore(ZeroDBJobStore())  # auto-provisions ZeroDB
scheduler.add_job(daily_report, 'cron', hour=6)
scheduler.start()
```

That's it. Jobs persist across restarts with zero infrastructure.

## How It Works

1. On first use, `ZeroDBJobStore` auto-provisions a free ZeroDB project
2. Jobs are serialized and stored in a ZeroDB NoSQL table (`apscheduler_jobs`)
3. `get_due_jobs()` queries by `next_run_time` for efficient scheduling
4. Credentials are saved to `~/.zerodb/config.json` for future runs

## Configuration

### Explicit Credentials

```python
store = ZeroDBJobStore(
    api_key="your-api-key",
    project_id="your-project-id",
)
```

### Environment Variables

```bash
export ZERODB_API_KEY="your-api-key"
export ZERODB_PROJECT_ID="your-project-id"
```

### Custom Table Name

```python
store = ZeroDBJobStore(table_name="my_scheduler_jobs")
```

## Credential Resolution Order

1. Constructor arguments (`api_key`, `project_id`)
2. Environment variables (`ZERODB_API_KEY`, `ZERODB_PROJECT_ID`)
3. Config file (`~/.zerodb/config.json`)
4. Auto-provision (free, no signup required)

## APScheduler Compatibility

`ZeroDBJobStore` implements APScheduler's `BaseJobStore` interface:

| Method | Description |
|--------|-------------|
| `add_job(job)` | Store a job |
| `update_job(job)` | Update an existing job |
| `remove_job(job_id)` | Remove a job |
| `lookup_job(job_id)` | Find a specific job |
| `get_due_jobs(now)` | Get jobs ready to run |
| `get_next_run_time()` | Next scheduled time |
| `get_all_jobs()` | List all jobs |
| `remove_all_jobs()` | Clear all jobs |

## Examples

### Interval Scheduling

```python
scheduler.add_job(check_health, 'interval', minutes=5)
```

### Cron Scheduling

```python
scheduler.add_job(weekly_cleanup, 'cron', day_of_week='sun', hour=3)
```

### Multiple Job Stores

```python
from apscheduler.jobstores.memory import MemoryJobStore

scheduler.add_jobstore(MemoryJobStore(), 'volatile')
scheduler.add_jobstore(ZeroDBJobStore(), 'persistent')

scheduler.add_job(temp_task, 'interval', seconds=10, jobstore='volatile')
scheduler.add_job(important_task, 'cron', hour=6, jobstore='persistent')
```

## License

MIT

---

### Powered by ZeroDB + AINative

[ZeroDB](https://docs.ainative.studio) is a serverless database with auto-provisioning, vector search, and NoSQL tables. Build AI-native apps without managing infrastructure.

- [Documentation](https://docs.ainative.studio)
- [GitHub](https://github.com/AINative-Studio)
- [Discord](https://discord.gg/ainative)
