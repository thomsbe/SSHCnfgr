from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from .paths import (
    DB_PATH,
    LEGACY_APP_SETTINGS_PATH,
    SSH_DIR,
    ensure_private_dir,
    set_private_permissions,
)

DEFAULT_DARK_THEME = "textual-dark"
DEFAULT_LIGHT_THEME = "textual-light"


def _read_ui_table(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    ui_data = raw.get("ui")
    return ui_data if isinstance(ui_data, dict) else None


def load_ui_theme(path: Path | None = None) -> bool:
    """Liest den Dark-Mode-Status aus der zentralen sshcnfgr.toml.

    Rueckgabe: True = dark, False = light.
    """
    return load_ui_theme_name(path) != DEFAULT_LIGHT_THEME


def load_ui_theme_name(path: Path | None = None) -> str:
    """Liest den gespeicherten Textual-Theme-Namen aus sshcnfgr.toml (mit Legacy-Fallback)."""
    target = path if path is not None else DB_PATH
    ui_data = _read_ui_table(target)
    if ui_data is None and path is None:
        ui_data = _read_ui_table(LEGACY_APP_SETTINGS_PATH)
    if ui_data is None:
        return DEFAULT_DARK_THEME

    theme_name = ui_data.get("theme")
    if isinstance(theme_name, str) and theme_name.strip():
        return theme_name.strip()

    is_dark = bool(ui_data.get("dark", True))
    return DEFAULT_DARK_THEME if is_dark else DEFAULT_LIGHT_THEME


def save_ui_theme(dark: bool, path: Path | None = None) -> None:
    """Speichert den Dark-Mode-Status in sshcnfgr.toml."""
    theme_name = DEFAULT_DARK_THEME if dark else DEFAULT_LIGHT_THEME
    save_ui_theme_name(theme_name, path)


def save_ui_theme_name(theme_name: str, path: Path | None = None) -> None:
    """Speichert den Textual-Theme-Namen im [ui]-Abschnitt der zentralen sshcnfgr.toml."""
    target = path if path is not None else DB_PATH
    if target.parent == SSH_DIR:
        ensure_private_dir(target.parent)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {}
    if target.exists():
        try:
            loaded = tomllib.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}

    payload["ui"] = {
        "theme": theme_name,
        "dark": theme_name != DEFAULT_LIGHT_THEME,
    }

    tmp_path = target.with_name(target.name + ".tmp")
    tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    set_private_permissions(tmp_path)
    tmp_path.replace(target)
