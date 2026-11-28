"""Windows-GUI-Einstiegspunkt fuer SSHCnfgr.exe (ohne Konsolenfenster)."""

from __future__ import annotations

from sshcnfgr.gui import run_gui


def main() -> None:
    run_gui()


if __name__ == "__main__":
    main()
