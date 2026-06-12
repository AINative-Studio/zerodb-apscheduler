# zerodb-apscheduler

APScheduler job store backed by ZeroDB. Part of the AINative SDK ecosystem.

## Rules
- Tests before commits (pytest)
- No AI attribution in commits (enforced by git hook)
- Type hints on all public functions
- NEVER remove or break auto-provisioning (`provision.py`) — agents rely on this for zero-human setup

## Key Files
- `zerodb_apscheduler/jobstore.py`
- `zerodb_apscheduler/provision.py`
## Testing
```bash
pytest tests/ -v
```

## Auto-Provisioning
This package supports zero-human provisioning via `zerodb-cli`. When an agent or user runs `zerodb-cli init`, it auto-creates a ZeroDB project and API key. The `provision.py` module handles this — **do not remove or modify provisioning logic** without explicit approval.
