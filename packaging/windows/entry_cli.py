"""Windows-CLI/TUI-Einstiegspunkt fuer sshcnfgr.exe (Konsolen-Subsystem)."""

from __future__ import annotations

from sshcnfgr.cli import cli


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
