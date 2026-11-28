"""Erzeugt PNG- (256x256) und Multi-Resolution-ICO-Icons aus assets/sshcnfgr.svg.

Nutzt PySide6 (QtGui/QtSvg) ohne zusaetzliche externe Tools wie ImageMagick oder Pillow.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)


def _render_png_bytes(svg_path: Path, size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QIcon

    icon = QIcon(str(svg_path))
    if icon.isNull():
        raise RuntimeError(f"SVG-Icon konnte nicht geladen werden: {svg_path}")

    pixmap = icon.pixmap(size, size)
    if pixmap.isNull():
        raise RuntimeError(f"Pixmap ({size}x{size}) konnte nicht gerendert werden: {svg_path}")

    buf = QBuffer()
    if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("QBuffer konnte nicht zum Schreiben geoeffnet werden")
    if not pixmap.save(buf, "PNG"):
        raise RuntimeError(f"PNG-Export fehlgeschlagen fuer Groesse {size}x{size}")
    return bytes(buf.data())


def _pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    """Verpackt PNG-Puffer als gueltige Windows-ICO-Datei (Vista+ PNG-in-ICO-Format)."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries: list[bytes] = []
    payloads: list[bytes] = []

    for size, png_data in images:
        # Im ICO-Header wird 256px als 0 kodiert.
        dim = 0 if size >= 256 else size
        entry = struct.pack(
            "<BBBBHHII",
            dim,
            dim,
            0,  # color count
            0,  # reserved
            1,  # planes
            32,  # bits per pixel
            len(png_data),
            offset,
        )
        entries.append(entry)
        payloads.append(png_data)
        offset += len(png_data)

    return header + b"".join(entries) + b"".join(payloads)


def generate_icons(svg_path: Path, out_dir: Path) -> tuple[Path, Path]:
    """Rendert sshcnfgr.png (256x256) und sshcnfgr.ico (16..256px) nach out_dir."""
    if not svg_path.exists():
        raise FileNotFoundError(f"SVG-Datei nicht gefunden: {svg_path}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[tuple[int, bytes]] = [
        (size, _render_png_bytes(svg_path, size)) for size in ICO_SIZES
    ]

    png_256 = dict(rendered)[256]
    png_path = out_dir / "sshcnfgr.png"
    png_path.write_bytes(png_256)

    ico_path = out_dir / "sshcnfgr.ico"
    ico_path.write_bytes(_pack_ico(rendered))

    return png_path, ico_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Erzeugt PNG- und ICO-Icons aus sshcnfgr.svg")
    parser.add_argument("--svg", type=Path, required=True, help="Pfad zur Quell-SVG-Datei")
    parser.add_argument("--out-dir", type=Path, required=True, help="Zielverzeichnis")
    args = parser.parse_args(argv)

    png_path, ico_path = generate_icons(args.svg, args.out_dir)
    print(
        f"Icons erzeugt: {png_path} ({png_path.stat().st_size} B), "
        f"{ico_path} ({ico_path.stat().st_size} B)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
