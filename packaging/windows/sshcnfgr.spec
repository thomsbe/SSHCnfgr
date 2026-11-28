# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec fuer ein gemeinsames Windows-onedir-Bundle (GUI + CLI/TUI).

Baut zwei kleine Starter im selben Zielverzeichnis, die sich den gemeinsamen
`_internal`-Ordner (Python + PySide6/Qt6 + Textual) teilen:
  - SSHCnfgr.exe: Windows-GUI-Subsystem (kein Konsolenfenster beim Doppelklick)
  - sshcnfgr.exe: Konsolen-Subsystem (CLI, TUI und `sshcnfgr gui` im Terminal)
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT_DIR = Path(SPECPATH).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
ASSETS_DIR = SRC_DIR / "sshcnfgr" / "assets"
ICON_STAGE_DIR = ROOT_DIR / "build" / "windows" / "icons"

ICO_FILE = ICON_STAGE_DIR / "sshcnfgr.ico"
PNG_FILE = ICON_STAGE_DIR / "sshcnfgr.png"
SVG_FILE = ASSETS_DIR / "sshcnfgr.svg"

datas: list[tuple[str, str]] = [
    (str(SRC_DIR / "sshcnfgr" / "tui.tcss"), "sshcnfgr"),
    (str(SVG_FILE), "sshcnfgr/assets"),
]
if PNG_FILE.exists():
    datas.append((str(PNG_FILE), "sshcnfgr/assets"))
if ICO_FILE.exists():
    datas.append((str(ICO_FILE), "sshcnfgr/assets"))

hiddenimports = collect_submodules("sshcnfgr")
icon_arg = str(ICO_FILE) if ICO_FILE.exists() else None

a_gui = Analysis(
    [str(ROOT_DIR / "packaging" / "windows" / "entry_gui.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="SSHCnfgr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)

a_cli = Analysis(
    [str(ROOT_DIR / "packaging" / "windows" / "entry_cli.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="sshcnfgr-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SSHCnfgr",
)
