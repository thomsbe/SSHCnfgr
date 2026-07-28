from __future__ import annotations

from pathlib import Path

APP_DIR = Path.home() / ".config" / "sshcnfgr"
DB_PATH = APP_DIR / "hosts.toml"
GENERATED_CONFIG_PATH = APP_DIR / "config.generated"
LOG_PATH = APP_DIR / "sshcnfgr.log"


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR
