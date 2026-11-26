# Contributing to SSHCnfgr

Thank you for your interest in contributing to **SSHCnfgr**!

## Development Setup

SSHCnfgr uses Python 3.12+ and [uv](https://docs.astral.sh/uv/) for dependency and environment management.

```bash
git clone https://github.com/thomsbe/SSHCnfgr.git
cd SSHCnfgr
uv sync --extra dev --extra qt
```

## Running Checks & Tests

Before opening a pull request, please ensure linting and tests pass:

```bash
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest -v
uv run sshcnfgr --help
```

## Guidelines

- Keep changes focused and backward-compatible with existing `sshcnfgr.toml` / `hosts.toml` schemas.
- Never read or store private SSH key contents — only paths and public-key metadata.
- Keep core business logic (`model.py`, `store.py`, `importer.py`, `generator.py`, `identities.py`, `dedup.py`) independent of UI frameworks so TUI, Qt6 GUI, and CLI all share the same logic.
- When changing the data model (`model.py`), update `store.py` and `generator.py` accordingly and add unit tests under `tests/`.

## Submitting Changes

1. Fork the repository and create a topic branch from `main`.
2. Make your changes and add or update tests.
3. Run `ruff check .` and `pytest`.
4. Open a pull request describing the motivation and changes clearly.
