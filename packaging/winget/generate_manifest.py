"""Erzeugt Winget-Manifestdateien (Schema 1.6.0) fuer microsoft/winget-pkgs.

Nutzt die GitHub-Release-URL und SHA-256-Pruefsumme des Inno-Setup-Installers,
sodass das Ergebnis direkt mit `winget validate --manifest <ordner>` geprueft
und per PR bzw. `wingetcreate submit` eingereicht werden kann.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PACKAGE_ID = "ThomsBe.SSHCnfgr"
MANIFEST_VERSION = "1.6.0"
INNO_PRODUCT_CODE = "{8E6A5B2C-4F1D-4C9A-9D3B-7A6E5C1B2D4E}_is1"
REPO_URL = "https://github.com/thomsbe/SSHCnfgr"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _build_version_yaml(version: str) -> str:
    return (
        "# Created for SSHCnfgr Windows Release\n"
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.{MANIFEST_VERSION}.schema.json\n"
        "\n"
        f"PackageIdentifier: {PACKAGE_ID}\n"
        f"PackageVersion: {version}\n"
        "DefaultLocale: en-US\n"
        "ManifestType: version\n"
        f"ManifestVersion: {MANIFEST_VERSION}\n"
    )


def _build_installer_yaml(version: str, installer_url: str, sha256: str) -> str:
    return (
        "# Created for SSHCnfgr Windows Release\n"
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.{MANIFEST_VERSION}.schema.json\n"
        "\n"
        f"PackageIdentifier: {PACKAGE_ID}\n"
        f"PackageVersion: {version}\n"
        "InstallerLocale: en-US\n"
        "InstallerType: inno\n"
        "UpgradeBehavior: install\n"
        "Commands:\n"
        "  - sshcnfgr\n"
        "AppsAndFeaturesEntries:\n"
        "  - DisplayName: SSHCnfgr\n"
        "    Publisher: Thomas Baer\n"
        f"    ProductCode: '{INNO_PRODUCT_CODE}'\n"
        "    InstallerType: inno\n"
        "Installers:\n"
        "  - Architecture: x64\n"
        "    Scope: user\n"
        f"    InstallerUrl: {installer_url}\n"
        f"    InstallerSha256: {sha256.upper()}\n"
        "    InstallerSwitches:\n"
        "      Custom: /CURRENTUSER\n"
        "  - Architecture: x64\n"
        "    Scope: machine\n"
        f"    InstallerUrl: {installer_url}\n"
        f"    InstallerSha256: {sha256.upper()}\n"
        "    InstallerSwitches:\n"
        "      Custom: /ALLUSERS\n"
        "ManifestType: installer\n"
        f"ManifestVersion: {MANIFEST_VERSION}\n"
    )


def _build_default_locale_yaml(version: str) -> str:
    return (
        "# Created for SSHCnfgr Windows Release\n"
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.{MANIFEST_VERSION}.schema.json\n"
        "\n"
        f"PackageIdentifier: {PACKAGE_ID}\n"
        f"PackageVersion: {version}\n"
        "PackageLocale: en-US\n"
        "Publisher: Thomas Baer\n"
        f"PublisherUrl: {REPO_URL}\n"
        f"PublisherSupportUrl: {REPO_URL}/issues\n"
        "Author: Thomas Baer\n"
        "PackageName: SSHCnfgr\n"
        f"PackageUrl: {REPO_URL}\n"
        "License: MIT\n"
        f"LicenseUrl: {REPO_URL}/blob/main/LICENSE\n"
        "ShortDescription: Manage OpenSSH hosts, groups, and identities "
        "from a single TOML file via Qt6 GUI, Textual TUI, and CLI.\n"
        "Description: |-\n"
        "  SSHCnfgr manages OpenSSH host configurations, groups, and SSH identity profiles\n"
        "  from a single TOML file (~/.ssh/sshcnfgr.toml) and generates clean OpenSSH configs\n"
        "  containing only enabled hosts. Includes a Qt6 desktop GUI, a Textual TUI, a Click CLI,\n"
        "  duplicate detection with optional DNS checks, and automatic timestamped backups.\n"
        "Moniker: sshcnfgr\n"
        "Tags:\n"
        "  - ssh\n"
        "  - openssh\n"
        "  - config\n"
        "  - devops\n"
        "  - qt\n"
        "  - tui\n"
        f"ReleaseNotesUrl: {REPO_URL}/releases/tag/v{version}\n"
        "ManifestType: defaultLocale\n"
        f"ManifestVersion: {MANIFEST_VERSION}\n"
    )


def _build_de_locale_yaml(version: str) -> str:
    return (
        "# Created for SSHCnfgr Windows Release\n"
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.locale.{MANIFEST_VERSION}.schema.json\n"
        "\n"
        f"PackageIdentifier: {PACKAGE_ID}\n"
        f"PackageVersion: {version}\n"
        "PackageLocale: de-DE\n"
        "Publisher: Thomas Baer\n"
        f"PublisherUrl: {REPO_URL}\n"
        f"PublisherSupportUrl: {REPO_URL}/issues\n"
        "Author: Thomas Baer\n"
        "PackageName: SSHCnfgr\n"
        f"PackageUrl: {REPO_URL}\n"
        "License: MIT\n"
        f"LicenseUrl: {REPO_URL}/blob/main/LICENSE\n"
        "ShortDescription: OpenSSH-Hosts, Gruppen und Identities ueber eine zentrale "
        "TOML-Datei per Qt6-GUI, Textual-TUI und CLI verwalten.\n"
        f"ReleaseNotesUrl: {REPO_URL}/releases/tag/v{version}\n"
        "ManifestType: locale\n"
        f"ManifestVersion: {MANIFEST_VERSION}\n"
    )


def generate_winget_manifests(
    *,
    version: str,
    sha256: str,
    out_dir: Path,
    installer_url: str | None = None,
) -> list[Path]:
    """Schreibt die vollstaendige Winget-Manifest-Struktur fuer ein Release."""
    cleaned_version = version.strip().lstrip("v")
    if not cleaned_version:
        raise ValueError("version darf nicht leer sein")
    cleaned_sha = sha256.strip()
    if not SHA256_RE.match(cleaned_sha):
        raise ValueError(f"sha256 muss genau 64 Hex-Zeichen enthalten, erhalten: {sha256!r}")

    default_url = (
        f"{REPO_URL}/releases/download/v{cleaned_version}/"
        f"SSHCnfgr-{cleaned_version}-x64-setup.exe"
    )
    url = installer_url.strip() if installer_url else default_url

    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        f"{PACKAGE_ID}.yaml": _build_version_yaml(cleaned_version),
        f"{PACKAGE_ID}.installer.yaml": _build_installer_yaml(cleaned_version, url, cleaned_sha),
        f"{PACKAGE_ID}.locale.en-US.yaml": _build_default_locale_yaml(cleaned_version),
        f"{PACKAGE_ID}.locale.de-DE.yaml": _build_de_locale_yaml(cleaned_version),
    }

    written: list[Path] = []
    for filename, content in files.items():
        target = out_dir / filename
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt Winget-Manifeste fuer ThomsBe.SSHCnfgr"
    )
    parser.add_argument("--version", required=True, help="Release-Version, z. B. 1.0.0")
    parser.add_argument("--sha256", required=True, help="SHA-256-Hash der Setup-EXE (64 Hex)")
    parser.add_argument("--out-dir", type=Path, required=True, help="Zielverzeichnis")
    parser.add_argument(
        "--installer-url",
        default=None,
        help="Optionale abweichende Download-URL (Standard: GitHub Release URL)",
    )
    args = parser.parse_args(argv)

    written = generate_winget_manifests(
        version=args.version,
        sha256=args.sha256,
        out_dir=args.out_dir,
        installer_url=args.installer_url,
    )
    for path in written:
        print(f"Geschrieben: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
