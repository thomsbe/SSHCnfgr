"""Optionale Qt6 Desktop-GUI (PySide6) fuer SSHCnfgr (Wayland und X11)."""

from __future__ import annotations

import sys


def run_gui() -> None:
    """Startet die Qt6-GUI.

    Qt6 waehlt unter Linux automatisch das passende Plattform-Plugin
    (Wayland oder X11/xcb).
    """
    from PySide6.QtWidgets import QApplication

    from .main_window import SSHCnfgrWindow

    app = QApplication.instance()
    created_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("SSHCnfgr")
    app.setOrganizationName("SSHCnfgr")

    window = SSHCnfgrWindow()
    window.show()

    if created_app:
        sys.exit(app.exec())
