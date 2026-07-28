from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from .paths import APP_SETTINGS_PATH, ensure_app_dir


def load_ui_theme(path: Path = APP_SETTINGS_PATH) -> bool:
    """Liest den Dark-Mode-Status aus app.toml.

    Rueckgabe: True = dark, False = light.
    """
    if not path.exists():
        return True

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True

    ui_data = raw.get("ui", {})
    if not isinstance(ui_data, dict):
        return True

    return bool(ui_data.get("dark", True))


def save_ui_theme(dark: bool, path: Path = APP_SETTINGS_PATH) -> None:
    """Speichert den Dark-Mode-Status in app.toml."""
    ensure_app_dir()
    payload = {"ui": {"dark": dark}}

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)
