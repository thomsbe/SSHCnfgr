from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None


def _load_module(name: str, rel_path: str):
    module_path = ROOT_DIR / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WingetManifestTests(unittest.TestCase):
    def test_generate_winget_manifests_writes_all_expected_files(self) -> None:
        mod = _load_module("winget_manifest_gen", "packaging/winget/generate_manifest.py")
        sha = "a" * 64

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "1.0.0"
            written = mod.generate_winget_manifests(version="v1.0.0", sha256=sha, out_dir=out_dir)

            names = {p.name for p in written}
            self.assertEqual(
                names,
                {
                    "ThomsBe.SSHCnfgr.yaml",
                    "ThomsBe.SSHCnfgr.installer.yaml",
                    "ThomsBe.SSHCnfgr.locale.en-US.yaml",
                    "ThomsBe.SSHCnfgr.locale.de-DE.yaml",
                },
            )
            installer_yaml = (out_dir / "ThomsBe.SSHCnfgr.installer.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("PackageVersion: 1.0.0", installer_yaml)
            self.assertIn("InstallerType: inno", installer_yaml)
            self.assertIn(f"InstallerSha256: {sha.upper()}", installer_yaml)
            self.assertIn("SSHCnfgr-1.0.0-x64-setup.exe", installer_yaml)

    def test_generate_winget_manifests_rejects_invalid_sha256(self) -> None:
        mod = _load_module("winget_manifest_gen", "packaging/winget/generate_manifest.py")
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                mod.generate_winget_manifests(
                    version="1.0.0",
                    sha256="too-short",
                    out_dir=Path(tmp_dir),
                )


@unittest.skipUnless(HAS_PYSIDE6, "PySide6-Essentials nicht installiert")
class WindowsIconGeneratorTests(unittest.TestCase):
    def test_generate_icons_produces_valid_png_and_multi_res_ico(self) -> None:
        mod = _load_module("win_icon_gen", "packaging/windows/generate_icons.py")
        svg_path = ROOT_DIR / "src" / "sshcnfgr" / "assets" / "sshcnfgr.svg"

        with tempfile.TemporaryDirectory() as tmp_dir:
            png_path, ico_path = mod.generate_icons(svg_path, Path(tmp_dir))

            png_bytes = png_path.read_bytes()
            self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

            ico_bytes = ico_path.read_bytes()
            reserved, ico_type, count = struct.unpack("<HHH", ico_bytes[:6])
            self.assertEqual((reserved, ico_type, count), (0, 1, len(mod.ICO_SIZES)))


if __name__ == "__main__":
    unittest.main()
