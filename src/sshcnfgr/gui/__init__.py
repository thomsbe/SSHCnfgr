"""Optionale Qt6 Desktop-GUI (PySide6) fuer SSHCnfgr (Wayland und X11)."""

from __future__ import annotations

import sys
from pathlib import Path


def _icon_path() -> Path:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    png_icon = assets_dir / "sshcnfgr.png"
    if png_icon.exists():
        return png_icon
    return assets_dir / "sshcnfgr.svg"


def run_gui() -> None:
    """Startet die Qt6-GUI.

    Qt6 waehlt unter Linux automatisch das passende Plattform-Plugin
    (Wayland oder X11/xcb).
    """
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
    app.setDesktopFileName("de.tbaer.sshcnfgr")

    icon_file = _icon_path()
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = SSHCnfgrWindow()
    if icon_file.exists():
        window.setWindowIcon(QIcon(str(icon_file)))
    window.show()

    if created_app:
        sys.exit(app.exec())
