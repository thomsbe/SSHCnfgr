# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (with PEP 440 pre-release tags).

## [0.1.0b1] - 2026-11-26

### Added
- **Single-file TOML storage in `~/.ssh/sshcnfgr.toml`:** Works uniformly on Linux, macOS, and Windows right next to `~/.ssh/config`, with automatic `0600` permissions on POSIX and integrated `[ui]` theme settings. Seamless fallback/migration from legacy `~/.config/sshcnfgr/hosts.toml`.
- **Direct `uvx` launch:** Running `sshcnfgr` (or `uvx sshcnfgr`) without a subcommand launches the Textual TUI directly; added `--version` and optional `--log-file` CLI flags (no stray log files created by default).
- **Duplicate detection & interactive merge (`dedup.py`):** Groups active hosts sharing the same effective target `(HostName, Port, User)`, detects conflicting fields (including case-insensitive `extra_options`), merges non-conflicting fields/groups/tags, and lets users disable or delete discarded duplicates.
- **TUI duplicate review screen (`Ctrl+U`):** Interactive comparison table, conflict selectors, live preview, and transactional saving.
- **Optional Qt6 desktop GUI (`sshcnfgr gui`):** Installable via `sshcnfgr[qt]` (`PySide6-Essentials`), supporting Wayland, X11, macOS, and Windows with tabs for Hosts (search, filter, `extra_options` editor, file pickers), Groups, Identities, Config Preview, and an interactive Duplicate Review dialog.
- **Automatic timestamped backups:** Backups (`*.bak.YYYYMMDD-HHMMSS`) are created before overwriting `sshcnfgr.toml` or generated OpenSSH config files.
- **Automated test suite (`tests/`):** Unit tests for core logic, duplicate merging, Textual Pilot TUI flows, and headless Qt6 GUI tests.

### Fixed
- Upgraded Textual theme switching from legacy `App.dark` to Textual 6+/8.x `App.theme`.
- Importer now supports `Key=Value` syntax and terminates active host blocks at `Match` blocks instead of leaking directives.
- Generator now emits global `Include` directives before host blocks, keeps `Host *` defaults at the end, and writes generated files with `0600` permissions on POSIX.
- Case-insensitive resolution for `IdentityFile`, `IdentityAgent`, `User`, and `Port` in `global_options` / `extra_options`.
- TUI form now clears `port` properly when emptied, persists `Toggle Aktiv`, clears form fields on delete, and suppresses `stderr` logging during TUI execution.
- `identities scan` now preserves manually disabled (`enabled = false`) identity profiles.

## [0.1.0a1] - 2026-07-28

### Added
- Initial Alpha MVP with Click CLI, Textual TUI, TOML persistence (`hosts.toml`), OpenSSH config import/generation, host groups, identity scanning from `~/.ssh`, and persistent theme toggle.
