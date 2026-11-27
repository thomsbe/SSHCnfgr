# SSHCnfgr

> **English speaker?** Jump to the [English Summary](#english-summary) at the bottom.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/thomsbe/SSHCnfgr/blob/main/LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)
[![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-brightgreen.svg)](https://pypi.org/project/sshcnfgr/)

**SSHCnfgr** verwaltet deine OpenSSH-Hosts, Gruppen und Identities über eine einzige, saubere TOML-Datei (`~/.ssh/sshcnfgr.toml`) — per **Textual-TUI**, optionaler **Qt6-Desktop-GUI** (Wayland/X11/macOS/Windows) oder **Click-CLI**.

## Highlights

- **Eine einzige Datei neben `~/.ssh/config`:** Alles liegt in `~/.ssh/sshcnfgr.toml` (auf Linux/macOS automatisch mit `0600`-Rechten, unter Windows in `%USERPROFILE%\.ssh\sshcnfgr.toml`) — ideal für den direkten Start per `uvx`.
- **TOML als Source of Truth:** Deaktivierte Hosts bleiben in der Datenbank erhalten, landen aber nicht in der generierten OpenSSH-Config (`~/.ssh/config.generated`, ebenfalls `0600`).
- **Dubletten finden & zusammenführen (inkl. optionalem DNS-Check):** Erkennt Hosts mit gleichem Ziel (`HostName` + effektiver `Port` + effektiver `User`) sowie auf Knopfdruck (**„Per DNS prüfen“**) auch versteckte Dubletten zwischen Hostname und IP (inkl. PTR-Hinweis), zeigt Feld-Konflikte übersichtlich an und führt Einträge interaktiv zusammen.
- **DNS-Anreicherung (FQDN + IP) & Alias-Generator (`USER@kurzname`):** Ergänzt auf Knopfdruck (einzeln oder als Sammel-Aktion) Kurznamen um Domain-FQDN + IP (und prüft reine IPs per FCrDNS), speichert FQDN und IP sauber gemeinsam in `sshcnfgr.toml` sowie als `# IP:`-Kommentar (verlustfreier Roundtrip mit `import`/`generate`) und benennt Einträge per Klick konsistent nach `USER@kurzname` um — ideal für die VS-Code-Remote-SSH-Liste.
- **Gruppen-Reihenfolge (Drag & Drop) & `Match originalhost`-Regeln:** Sortiere Gruppen in der Qt6-GUI frei per Drag & Drop — `config.generated` (und damit auch **VS Code Remote-SSH**) listet Hosts nach ihrer ersten Gruppe in genau dieser Reihenfolge. Gruppen-Defaults (`Identity`, `User`, `Port`, `ProxyJump`, `IdentitiesOnly`, …) werden als saubere OpenSSH-`Match originalhost`-Blöcke erzeugt.
- **Mehrfachauswahl & Sammel-Aktionen (Qt6-GUI):** Mehrere Hosts per `Ctrl+Klick`, `Shift+Klick` oder `Ctrl+A` (auch nach Live-Suche!) markieren und per Sammel-Aktionen-Leiste oder Rechtsklick in einem Rutsch einer Gruppe zuweisen, als 1. Gruppe setzen, aktivieren/deaktivieren oder löschen.
- **TUI, Qt6-GUI & CLI:** Im Terminal mit Textual, auf dem Desktop optional mit PySide6/Qt6 (Live-Suche, Gruppen-/Identity-Tabs, `extra_options`-Editor, Config-Vorschau) oder skriptbar über die CLI.
- **Sicherheitsnetz:** Keine Speicherung privater Schlüssel-Inhalte (nur Pfade & `.pub`-Metadaten), atomares Schreiben und automatische Zeitstempel-Backups (`*.bak.YYYYMMDD-HHMMSS`) vor jedem Überschreiben.

---

## Schnellstart mit `uv` / `uvx`

### Ohne Installation direkt ausführen (`uvx`)

```bash
# Textual-TUI direkt starten (legt ~/.ssh/sshcnfgr.toml bei Bedarf an)
uvx sshcnfgr

# Optionale Qt6 Desktop-GUI starten (Wayland / X11 / macOS / Windows)
uvx --from "sshcnfgr[qt]" sshcnfgr gui

# Bestehende ~/.ssh/config importieren
uvx sshcnfgr import --source ~/.ssh/config
```

### Dauerhaft als CLI-Tool installieren (`uv tool install`)

```bash
# Terminal-Version (TUI + CLI)
uv tool install sshcnfgr

# Inklusive Qt6 Desktop-GUI
uv tool install "sshcnfgr[qt]"

# Danach direkt nutzbar:
sshcnfgr            # startet die TUI
sshcnfgr gui        # startet die Qt6-GUI
sshcnfgr --help     # zeigt alle Kommandos
```

*(Falls `uv` noch nicht installiert ist: `curl -LsSf https://astral.sh/uv/install.sh | sh` auf Linux/macOS bzw. `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` unter Windows.)*

### Linux AppImage (ohne Python / ohne `uv`)

Für Linux-Desktop-Nutzer (z. B. Linux Mint, Ubuntu, Debian, Fedora) steht bei jedem [GitHub Release](https://github.com/thomsbe/SSHCnfgr/releases) eine fertige `SSHCnfgr-*-x86_64.AppImage` inklusive gebündelter Qt6-GUI bereit — es werden weder Python noch `uv` benötigt.

#### Optimal: Integration & Auto-Update mit Gear Lever (empfohlen)

1. `SSHCnfgr-*-x86_64.AppImage` von den [GitHub Releases](https://github.com/thomsbe/SSHCnfgr/releases) herunterladen.
2. In **[Gear Lever](https://mijorus.it/projects/gearlever/)** (per Flatpak / Software-Verwaltung) öffnen und **„In Anwendungsmenü verschieben“** (*Move to the app menu*) klicken.
3. Fertig: Icon, Startmenü-Eintrag und Wayland/X11-Desktop-Integration werden automatisch eingerichtet.
4. **Auto-Update inklusive:** Im AppImage sind bereits `gh-releases-zsync`-Update-Metadaten eingebettet (`gh-releases-zsync|thomsbe|SSHCnfgr|latest|SSHCnfgr-*-x86_64.AppImage.zsync`), und jedes Release liefert automatisch die passende `.AppImage.zsync`-Datei mit. Gear Lever (und Topgrade) erkennt Updates damit von selbst und lädt per Delta-Update nur die geänderten Blöcke nach.

#### Direkt ohne Gear Lever starten

```bash
chmod +x SSHCnfgr-*-x86_64.AppImage
./SSHCnfgr-*-x86_64.AppImage          # startet direkt die Qt6 Desktop-GUI (wie Doppelklick)
./SSHCnfgr-*-x86_64.AppImage tui      # startet die Textual-TUI im Terminal
./SSHCnfgr-*-x86_64.AppImage --help   # alle CLI-Kommandos direkt nutzbar
```

*(Falls auf einem System kein `libfuse2` installiert ist, funktioniert der Start jederzeit mit `APPIMAGE_EXTRACT_AND_RUN=1 ./SSHCnfgr-*-x86_64.AppImage` oder `--appimage-extract-and-run`.)*

---

## Typischer Ablauf

1. **Vorhandene SSH-Config importieren** (deine `~/.ssh/config` wird nur gelesen):
   ```bash
   sshcnfgr import --source ~/.ssh/config
   ```
2. **Lokale SSH-Keys erfassen** (nur Pfade & `.pub`-Vorschau, keine Private Keys):
   ```bash
   sshcnfgr identities scan
   ```
3. **Hosts pflegen & Dubletten aufräumen:**
   - In der TUI (`sshcnfgr`) mit **`Ctrl+U`** oder Button **„Dubletten“**
   - Oder in der Qt6-GUI (`sshcnfgr gui`) über **„Dubletten…“** (`Ctrl+U`)
4. **OpenSSH-Config erzeugen:**
   ```bash
   sshcnfgr generate
   ```
   Standard-Ausgabe ist `~/.ssh/config.generated` (`0600`). Du kannst sie direkt per `Include` in deiner `~/.ssh/config` einbinden:
   ```sshconfig
   Include config.generated
   ```

---

## CLI-Übersicht

```bash
sshcnfgr                                              # TUI direkt starten
sshcnfgr tui                                          # TUI starten
sshcnfgr gui                                          # Qt6 Desktop-GUI starten ([qt]-Extra)
sshcnfgr import --source ~/.ssh/config                # OpenSSH-Config importieren
sshcnfgr generate --output ~/.ssh/config.generated    # OpenSSH-Config generieren
sshcnfgr identities scan                              # Keys aus ~/.ssh erfassen
sshcnfgr identities list                              # Bekannte Identities anzeigen
sshcnfgr groups set-identity prod id_ed25519          # Gruppen-Default-Identity setzen
sshcnfgr --version                                    # Version anzeigen
```

Optionales File-Logging (Standard: keine Logdatei):
```bash
sshcnfgr --verbose --log-file /tmp/sshcnfgr.log generate
```

---

## Dateien & Migration

| Datei | Zweck |
| --- | --- |
| `~/.ssh/sshcnfgr.toml` | Zentrale Source of Truth (Hosts, Gruppen, Identities, `global_options`, `[ui]`), `0600` auf POSIX |
| `~/.ssh/config.generated` | Generierte OpenSSH-Config (nur aktive Hosts, `Host *` am Ende), `0600` auf POSIX |
| `*.bak.YYYYMMDD-HHMMSS` | Automatisches Zeitstempel-Backup vor jedem Überschreiben |

> **Migration aus `0.1.0a1`:** Falls `~/.ssh/sshcnfgr.toml` noch nicht existiert, aber noch eine ältere `~/.config/sshcnfgr/hosts.toml` vorhanden ist, lädt SSHCnfgr diese automatisch und schreibt beim nächsten Speichern nach `~/.ssh/sshcnfgr.toml`.

---

## Entwicklung & Release

```bash
git clone https://github.com/thomsbe/SSHCnfgr.git
cd SSHCnfgr
uv sync --extra dev --extra qt

# Linting & Tests (inkl. Textual Pilot & Qt6 Offscreen)
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest -v
```

### Paket bauen & auf PyPI veröffentlichen

```bash
uv build
uv run twine check dist/*
uv publish
```

Weitere Dokumente: [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), [LICENSE](LICENSE) (MIT).

---

## English Summary

**SSHCnfgr** is a cross-platform (Linux, macOS, Windows) manager for OpenSSH host configurations backed by a **single TOML file** (`~/.ssh/sshcnfgr.toml`, `0600` permissions on POSIX) located right next to `~/.ssh/config`.

### Key Features
- **Single source of truth:** Manage hosts, groups, identity profiles, and global defaults in `~/.ssh/sshcnfgr.toml` and generate clean OpenSSH configs (`~/.ssh/config.generated`) containing only enabled hosts.
- **Duplicate detection & interactive merge:** Finds hosts pointing to the same effective `(HostName, Port, User)` target, highlights field conflicts, merges non-conflicting attributes, and lets you disable or delete duplicates safely.
- **Three interfaces:** Interactive **Textual TUI** (default), optional **Qt6 desktop GUI** (`PySide6-Essentials`, Wayland/X11/macOS/Windows), and **Click CLI**.
- **Safe by design:** Never reads or stores private SSH key contents; writes atomically with `0600` permissions and creates timestamped backups before overwriting.

### Quickstart
```bash
# Run directly with uvx
uvx sshcnfgr
uvx --from "sshcnfgr[qt]" sshcnfgr gui

# Or install globally as a tool
uv tool install sshcnfgr
uv tool install "sshcnfgr[qt]"

# Import existing OpenSSH config & generate
sshcnfgr import --source ~/.ssh/config
sshcnfgr generate
```

On Linux desktops (without Python or `uv`), download `SSHCnfgr-*-x86_64.AppImage` from [GitHub Releases](https://github.com/thomsbe/SSHCnfgr/releases). Open it in **Gear Lever** for one-click app-menu integration and automatic delta updates (`gh-releases-zsync` metadata and `.zsync` files are included), or make it executable (`chmod +x`) and run it directly (opens the Qt6 GUI by default; CLI/TUI arguments also work).

Licensed under the [MIT License](LICENSE). See [SECURITY.md](SECURITY.md) for security reporting and [CONTRIBUTING.md](CONTRIBUTING.md) for development details.
