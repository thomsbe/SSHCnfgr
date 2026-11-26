from __future__ import annotations

import os
from pathlib import Path

SSH_DIR = Path.home() / ".ssh"
DB_PATH = SSH_DIR / "sshcnfgr.toml"
GENERATED_CONFIG_PATH = SSH_DIR / "config.generated"

# Rueckwaertskompatible Aliase (Single-File-Design: UI-Settings liegen mit in sshcnfgr.toml)
APP_DIR = SSH_DIR
APP_SETTINGS_PATH = DB_PATH

# Legacy-Pfade aus 0.1.0a1 fuer nahtlose Uebernahme bestehender Daten
LEGACY_APP_DIR = Path.home() / ".config" / "sshcnfgr"
LEGACY_DB_PATH = LEGACY_APP_DIR / "hosts.toml"
LEGACY_APP_SETTINGS_PATH = LEGACY_APP_DIR / "app.toml"


def set_private_permissions(path: Path) -> None:
    """Setzt 0o600-Dateirechte auf POSIX-Systemen (Linux/macOS); No-Op unter Windows."""
    if os.name == "posix":
        os.chmod(path, 0o600)


def ensure_private_dir(path: Path) -> Path:
    """Stellt sicher, dass ein Zielverzeichnis existiert (0o700 auf POSIX bei Neuanlage)."""
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if not existed and os.name == "posix":
        os.chmod(path, 0o700)
    return path


def ensure_app_dir() -> Path:
    """Stellt sicher, dass ~/.ssh existiert."""
    return ensure_private_dir(SSH_DIR)
