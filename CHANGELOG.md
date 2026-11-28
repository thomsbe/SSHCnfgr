# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (with PEP 440 pre-release tags).

## [1.1.0] - 2026-11-28

Full Windows desktop support, standalone Windows installer (Inno Setup), and Winget packaging (`ThomsBe.SSHCnfgr`).

### Added
- **Windows x64 installer (`SSHCnfgr-*-x64-setup.exe`):** Automated GitHub Actions workflow (`windows-installer.yml` on `windows-latest`) bundling Python, `sshcnfgr`, and `PySide6-Essentials` via PyInstaller (`--onedir` with shared `_internal`: `SSHCnfgr.exe` GUI without console window + `sshcnfgr-cli.exe` / `bin/sshcnfgr.cmd` CLI/TUI on `PATH`) and Inno Setup 6 (per-user install without admin rights or optional machine-wide install, Start Menu/Desktop shortcuts, clean uninstaller, and automated silent install/uninstall smoke test in CI).
- **Automatic Windows `.ico`/`.png` icon generation:** `packaging/windows/generate_icons.py` renders multi-resolution `.ico` (16–256 px) and 256×256 `.png` icons directly from `src/sshcnfgr/assets/sshcnfgr.svg` via PySide6 without external imaging dependencies.
- **Winget manifest generator & optional auto-publish (`ThomsBe.SSHCnfgr`):** Added `packaging/winget/generate_manifest.py` (schema-validated against `winget validate`), release workflow artifacts, opt-in `publish-winget` release job, and documentation in `doc/windows-release.md`.
- **Windows Qt6 GUI CI coverage:** `.github/workflows/ci.yml` now installs `--extra qt` and executes the Qt6 GUI test suite across `windows-latest`, `macos-latest`, and `ubuntu-latest` (Python 3.12/3.13).

### Fixed
- **OpenSSH quoting for `IdentityFile` paths with spaces:** `generator.py` now quotes `IdentityFile` values containing whitespace (e.g. Windows user profiles like `C:\Users\Max Mustermann\.ssh\...`) in host, `Match originalhost`, and `Host *` blocks; `importer.py` strips matching outer quotes on import for lossless roundtrips.
- **UTF-8 BOM & CRLF tolerance:** `importer.py`, `store.py`, and `settings.py` now read files using `utf-8-sig` so configs or TOML files edited in Windows editors/PowerShell with a BOM parse cleanly.
- **Qt6 GUI Windows polish & `Ctrl+C` handling:** `gui/__init__.py` sets the Windows `AppUserModelID` (`de.tbaer.sshcnfgr`) for taskbar icon grouping, prefers `.ico` on Windows, brings the window to the foreground on startup (`raise_()` / `activateWindow()`), and installs a `SIGINT` handler with a 250 ms `QTimer` so `Ctrl+C` cleanly terminates `sshcnfgr gui` from terminals.

## [1.0.0] - 2026-11-27

First stable release (`Development Status :: 5 - Production/Stable`, installable directly via `uvx sshcnfgr` / `uv tool install sshcnfgr` without `--prerelease=allow`).

### Added
- **On-demand DNS duplicate detection (Name ↔ IP):** New **„Per DNS prüfen“** button (and `Ctrl+R` in TUI) in the duplicate review dialog/screen resolves hostnames in parallel (Forward DNS `Name → IP` + Reverse DNS `PTR` hints for bare IPs) without blocking the UI.
- **Union-Find IP grouping & smart HostName defaults:** Matches entries where one uses a hostname and another uses its IP (including dual-stack IPv4/IPv6), tags matches clearly as `Exakt` vs. `DNS (<ip>)`, shows resolved IPs/PTRs per candidate, defaults `HostName` conflict dropdowns to human-readable hostnames over bare IPs, and automatically preserves discarded bare IPs in `host.ip` during merge.
- **Structured `ip` field & lossless `# IP:` config roundtrip:** Hosts can now store an optional informational `ip` alongside an FQDN `host_name` in `~/.ssh/sshcnfgr.toml`. `config.generated` emits `  # IP: <ip>` directly beneath `HostName` (without breaking OpenSSH or creating duplicate VS Code entries), and `sshcnfgr import` reads `# IP:` comments back into `host.ip`.
- **On-demand DNS FQDN/IP enrichment (Qt6 GUI, single & bulk):** Expand short hostnames (e.g. `sdvdmg-mongodb` → `sdvdmg-mongodb.slub-dresden.de` + IPv4), upgrade bare IPs via Forward-Confirmed Reverse DNS (FCrDNS) while retaining the IP, or fill missing IPs on existing FQDNs without overwriting explicit CNAMEs.
- **VS-Code-friendly Alias Generator (`USER@kurzname`):** Single-host **„Name generieren“** button and bulk **„Aliase generieren“** action (with confirmation preview) rename host aliases cleanly to `USER@kurzname` (or `USER@ip` / `kurzname` fallback, with automatic `-2`/`-3` collision suffixes).

## [0.2.0b3] - 2026-11-26

### Added
- **Multi-select & bulk host actions (Qt6 GUI):** Select multiple hosts via `Ctrl+Click`, `Shift+Click`, or `Ctrl+A` (pairs great with live search filtering) and apply bulk actions from the new **Sammel-Aktionen** bar or right-click context menu: assign to group, set as primary (1st) group, remove from group, enable all, disable all, assign identity, or delete multiple hosts with confirmation.

## [0.2.0b2] - 2026-11-26

### Added
- **User-defined group ordering with Drag & Drop (Qt6 GUI):** Reorder groups via drag & drop or `▲` / `▼` buttons in the Groups tab; order is preserved in `~/.ssh/sshcnfgr.toml` instead of forced alphabetical sorting.
- **Grouped OpenSSH config generation (VS Code Remote-SSH friendly):** Active hosts are grouped by their primary (first) group in your custom group order (with clear section comments) so important hosts appear at the top in VS Code and `config.generated`.
- **Extended group defaults & `Match originalhost` blocks:** Groups now support default `user`, `port`, `identity`, and `extra_options` (e.g. `IdentitiesOnly yes`, `ProxyJump`), emitted as clean OpenSSH `Match originalhost alias1,alias2,...` blocks after host blocks and before `Host *`.

## [0.2.0b1] - 2026-11-26

### Added
- **Linux AppImage (`x86_64`) with Gear Lever auto-updates:** Automated GitHub Actions build workflow (`appimage.yml` on `ubuntu-22.04`) bundling Python, `sshcnfgr`, and `PySide6-Essentials` via PyInstaller and `appimagetool`.
- **Embedded `gh-releases-zsync` update metadata & `.zsync` artifacts:** Enables automatic delta updates in Gear Lever and AppImageUpdate directly from GitHub Releases.
- **Custom vector SVG icon & desktop metadata:** Added `src/sshcnfgr/assets/sshcnfgr.svg`, Freedesktop `.desktop` entry (`de.tbaer.sshcnfgr`), AppStream metainfo, and native Wayland/X11 window icon integration.
- **Smart AppImage entry point:** Launching the AppImage without arguments opens the Qt6 desktop GUI directly; passing arguments delegates to the standard CLI/TUI.

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
