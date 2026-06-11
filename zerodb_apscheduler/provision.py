"""
Auto-provisioning for ZeroDB.

Resolves credentials in order:
1. Explicit constructor args
2. Environment variables (ZERODB_API_KEY, ZERODB_PROJECT_ID)
3. Config file (~/.zerodb/config.json)
4. Auto-provision via Instant DB endpoint (free, no signup)
"""

import json
import os
from pathlib import Path

import requests

ZERODB_API_BASE = "https://api.ainative.studio"
INSTANT_DB_ENDPOINT = f"{ZERODB_API_BASE}/api/v1/public/instant-db"
CONFIG_DIR = Path.home() / ".zerodb"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config_file():
    """Load credentials from ~/.zerodb/config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            api_key = data.get("api_key")
            project_id = data.get("project_id")
            if api_key and project_id:
                return api_key, project_id
        except (json.JSONDecodeError, OSError):
            pass
    return None, None


def _save_config_file(api_key, project_id, claim_url=None):
    """Save credentials to ~/.zerodb/config.json."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"api_key": api_key, "project_id": project_id}
        if claim_url:
            data["claim_url"] = claim_url
        CONFIG_FILE.write_text(json.dumps(data, indent=2))
    except OSError:
        pass  # Best-effort -- don't crash if home dir is read-only


def _auto_provision():
    """Create an instant ZeroDB project (free, no signup required)."""
    resp = requests.post(
        INSTANT_DB_ENDPOINT,
        json={"source": "zerodb-apscheduler"},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    api_key = data["api_key"]
    project_id = data["project_id"]
    claim_url = data.get("claim_url")

    # Persist for future runs
    _save_config_file(api_key, project_id, claim_url)

    if claim_url:
        print(
            f"\n  zerodb-apscheduler: Auto-provisioned free project."
            f"\n  Claim it at: {claim_url}"
            f"\n  Project: {project_id}"
            f"\n  This message only appears once.\n"
        )

    return api_key, project_id


def resolve_credentials(api_key=None, project_id=None):
    """Resolve ZeroDB credentials from args, env, config, or auto-provision.

    Returns (api_key, project_id, base_url).
    """
    base_url = os.environ.get("ZERODB_BASE_URL", ZERODB_API_BASE)

    # 1. Explicit args
    if api_key and project_id:
        return api_key, project_id, base_url

    # 2. Environment variables
    env_key = os.environ.get("ZERODB_API_KEY")
    env_project = os.environ.get("ZERODB_PROJECT_ID")
    if env_key and env_project:
        return env_key, env_project, base_url

    # 3. Config file
    file_key, file_project = _load_config_file()
    if file_key and file_project:
        return file_key, file_project, base_url

    # 4. Auto-provision
    auto_key, auto_project = _auto_provision()
    return auto_key, auto_project, base_url
