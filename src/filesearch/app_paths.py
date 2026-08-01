from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "FileSearch"


def app_data_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def env_path() -> Path:
    return app_data_dir() / ".env"


def database_path() -> Path:
    return app_data_dir() / "filesearch.sqlite3"
