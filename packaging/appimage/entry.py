from __future__ import annotations

import sys

from sshcnfgr.cli import cli


def main() -> None:
    """AppImage-Einstiegspunkt.

    - Ohne Argumente (z. B. Doppelklick / Desktop-Starter): startet direkt die Qt6-GUI.
    - Mit Argumenten (z. B. `tui`, `import`, `generate`, `--help`): delegiert an die normale CLI.
    """
    if len(sys.argv) == 1:
        sys.argv.append("gui")
    cli()


if __name__ == "__main__":
    main()
