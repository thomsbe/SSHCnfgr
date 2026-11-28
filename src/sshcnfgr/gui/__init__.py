"""Optionale Qt6 Desktop-GUI (PySide6) fuer SSHCnfgr (Windows, macOS und Linux)."""

from __future__ import annotations

import ctypes
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

APP_ID = "de.tbaer.sshcnfgr"


def _icon_path() -> Path:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    candidates = (
        ("sshcnfgr.ico", "sshcnfgr.png", "sshcnfgr.svg")
        if sys.platform == "win32"
        else ("sshcnfgr.png", "sshcnfgr.svg")
    )
    for filename in candidates:
        candidate = assets_dir / filename
        if candidate.exists():
            return candidate
    return assets_dir / "sshcnfgr.svg"


def _configure_windows_app_id() -> None:
    """Setzt die Windows-AppUserModelID, damit die Taskleiste das App-Icon zuordnet."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def _install_sigint_handler(app: QApplication) -> QTimer | None:
    """Ermoeglicht sauberes Beenden per Ctrl+C im Terminal waehrend app.exec().

    Qt's C++-Eventloop blockiert ohne periodischen Python-Tick die Auslieferung von SIGINT.
    """
    from PySide6.QtCore import QTimer

    try:
        signal.signal(signal.SIGINT, lambda *_args: app.quit())
    except (ValueError, OSError):
        return None

    timer = QTimer(app)
    timer.setInterval(250)
    timer.timeout.connect(lambda: None)
    timer.start()
    return timer


def run_gui() -> None:
    """Startet die Qt6-GUI.

    Qt6 waehlt automatisch das passende Plattform-Plugin
    (Windows, macOS/cocoa, Wayland oder X11/xcb).
    """
    _configure_windows_app_id()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .main_window import SSHCnfgrWindow

    app = QApplication.instance()
    created_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("SSHCnfgr")
    app.setOrganizationName("SSHCnfgr")
    # Wichtig fuer Wayland, damit Panel/Taskleiste das .desktop-Icon zuordnen koennen.
    app.setDesktopFileName(APP_ID)

    icon_file = _icon_path()
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = SSHCnfgrWindow()
    if icon_file.exists():
        window.setWindowIcon(QIcon(str(icon_file)))
    window.show()
    window.raise_()
    window.activateWindow()

    if created_app:
        _sigint_timer = _install_sigint_handler(app)
        sys.exit(app.exec())
