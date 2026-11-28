# SSHCnfgr - Bearbeitungsstand und Uebergabeplan

## 1. Ziel dieses Dokuments

Dieses Dokument ist eine Uebergabe fuer andere Agenten/LLMs.
Es beschreibt:

- den aktuellen Implementierungsstand
- was bereits entschieden und umgesetzt wurde
- offene Punkte und Risiken
- konkrete naechste Schritte

Stand: 2026-07-28

## 2. Kurzstatus

SSHCnfgr ist ein lauffaehiges Alpha-MVP fuer das Verwalten von SSH-Hosts per Textual-TUI und Click-CLI.

Bereits umgesetzt:

- TOML als Source of Truth
- Import von SSH-Config
- Generierung einer OpenSSH-Config
- Host-, Group- und Identity-Modell
- Identity-Scan aus ~/.ssh
- Theme-Umschaltung in TUI mit Persistenz
- PyPI-freundliche Projektmetadaten (Alpha-Versionierung)

## 3. Architektur und Dateilayout

Wesentliche Dateien:

- AGENTS.md: Agentenregeln und Projekthinweise
- README.md: Nutzer- und Developer-Doku
- doc/project.md: Projektidee und Pflichtenheft
- docs/plan.md: dieses Uebergabe-Dokument

Python-Module:

- src/sshcnfgr/cli.py: Click-CLI mit Commands und Subcommands
- src/sshcnfgr/tui.py: Textual UI
- src/sshcnfgr/tui.tcss: Styling
- src/sshcnfgr/model.py: Datenmodell, Validierung, Resolver
- src/sshcnfgr/store.py: TOML Load/Save, atomisches Schreiben
- src/sshcnfgr/importer.py: SSH-Config Import
- src/sshcnfgr/generator.py: OpenSSH-Config Ausgabe
- src/sshcnfgr/identities.py: Discovery und Merge fuer SSH-Keys
- src/sshcnfgr/settings.py: App-Settings, aktuell Theme-Persistenz
- src/sshcnfgr/paths.py: Pfadkonstanten fuer App-Dateien

## 4. Datenmodell (Ist)

### 4.1 HostEntry

Host-Felder:

- id
- name
- enabled
- host_name
- user
- port
- identity
- identity_file
- groups
- tags
- extra_options

### 4.2 HostGroup

Group-Felder:

- name
- description
- identity

### 4.3 IdentityProfile

Identity-Felder:

- name
- identity_file
- source
- public_key_file
- public_key_preview
- enabled

### 4.4 HostDatabase

Enthaelt:

- groups
- identities
- global_options
- hosts

Resolver-Funktionen:

- resolve_identity_file(host)
- resolve_identity_agent(host)
- resolve_port(host)

## 5. TOML-Schema (Ist)

Datei: ~/.config/sshcnfgr/hosts.toml

Top-Level-Keys:

- groups (array of tables)
- identities (array of tables)
- global_options (table)
- hosts (array of tables)

Hinweis:

- global_options wird aktuell fuer importierte Host-Stern-Defaults verwendet (Host *)

## 6. Implementierte Features

### 6.1 CLI

Hauptcommands:

- sshcnfgr tui
- sshcnfgr import --source ...
- sshcnfgr generate --output ...

Subcommands:

- sshcnfgr identities scan
- sshcnfgr identities list
- sshcnfgr groups set-identity GROUP IDENTITY

### 6.2 Import

- Standard-Host-Bloecke werden importiert
- Doppelte Hostnamen bekommen Suffix
- Unbekannte Direktiven landen in extra_options
- Host * wird als globale Defaults in global_options importiert
- Wildcard-Hosts ausser Host * werden derzeit nicht als eigene Entitaeten importiert
- Direktiven vor dem ersten Host-Block gelten als globale Defaults und landen in global_options
- Include vor dem ersten Host-Block wird global uebernommen; Include innerhalb eines
  Host-Blocks bleibt als extra_option konditional am Host (OpenSSH-konform)
- Direktiven komplett uebersprungener Wildcard-Bloecke werden mit Warnung protokolliert
  und nicht uebernommen (kein Verlust an globale Optionen oder fremde Hosts)

### 6.3 Generate

- Deterministische Sortierung (alphabetisch)
- Nur enabled=true Hosts werden generiert
- global_options wird als Host * Block ausgegeben
- Host * Block steht am Dateiende, weil OpenSSH pro Parameter den ersten gefundenen
  Wert verwendet (sonst wuerden globale Defaults Host-Werte ueberschreiben)
- Globaler IdentityFile-Default wird nicht redundant in einzelne Host-Bloecke wiederholt
- Identity-Aufloesung:
  1) host.identity_file
  2) host.identity (IdentityProfile)
  3) group.identity (IdentityProfile)
  4) global_options IdentityFile

### 6.4 TUI

- Hosttabelle links
- Identitytabelle links
- Hostdetailformular rechts
- Group-Identity-Zuordnung (ueber ausgewahlte Identity + Gruppennamen)
- Identity-Scan aus ~/.ssh
- Identity aktivieren/deaktivieren
- Theme-Toggle per Ctrl+T
- Theme persistiert in ~/.config/sshcnfgr/app.toml
- Speichern validiert auf einer Kopie und committet erst bei Erfolg (transaktional)

### 6.5 Visualisierung indirekter Werte in Hosttabelle

- Port-Spalte zeigt bei fehlendem host.port den effektiven Port gedimmt an (inkl. Default 22)
- Identity-Spalte zeigt indirekte Zuordnung gedimmt an
- Wenn keine IdentityFile-Aufloesung greift, aber IdentityAgent effektiv ist:
  Anzeige als gedimmtes agent:<socket>

## 7. Wichtige Entscheidungen

- Fokus auf Lernbarkeit statt maximaler Feature-Breite
- Kleine, inkrementelle Aenderungen statt grosser Refactors
- Backward-Kompatibilitaet fuer vorhandene TOML-Daten beibehalten
- Keine privaten Schluesselinhalte speichern, nur Metadaten/Pfade

## 8. Was bereits getestet wurde

Smoke-Tests wurden mehrfach ausgefuehrt:

- uv run sshcnfgr --help
- Import und anschliessendes Generate
- identities scan/list
- groups set-identity
- Host-Stern-Fall mit IdentityFile und IdentityAgent

Ergebnis:

- Kernflows laufen
- kein statischer Fehler in geaenderten Python-Dateien

### 8.1 Bugfix-Paket 2026-07-28 (erledigt)

Nach einer Codekritik-Session wurden folgende Bugs gefixt:

- Generator: Host * Block wird jetzt am Dateiende ausgegeben (vorher am Anfang;
  haette dazu gefuehrt, dass globale Defaults Host-Werte beim echten ssh schlagen)
- Generator: globaler IdentityFile-Default wurde redundant in jeden Host-Block
  geschrieben; wird jetzt nur noch im Host-*-Block ausgegeben
- Importer: Direktiven vor dem ersten Host-Block wurden verworfen; landen jetzt
  korrekt in global_options
- Importer: Direktiven komplett uebersprungener Wildcard-Bloecke (z. B. Host *.internal)
  sickerten in global_options oder nachfolgende Hosts; werden jetzt mit Warnung ignoriert
- TUI action_save: validierte erst nach Mutation der In-Memory-DB; ein
  Validierungsfehler (z. B. doppelter Name) liess die App in einem kaputten Zustand
  zurueck. Jetzt wird auf einer Kopie validiert und erst bei Erfolg committet
- TUI: ungueltiger Port wurde still zu None; gibt jetzt eine Fehlermeldung
- store/generator: Zielverzeichnis von --output/Pfad wird bei Bedarf angelegt
  (vorher nur ~/.config/sshcnfgr)
- Aufraeumen: dead code (default_identity_file) entfernt, __version__ an
  pyproject.toml angeglichen (0.1.0a1), Textual-Import in cli.py lazy
- ruff-Baseline: 5 alte E501-Verstoesse behoben, `uv run --extra dev ruff check .`
  ist jetzt sauber

Verifikation:

- Import/Generate-Roundtrip mit Test-Config (globale Defaults, Host *, Wildcards,
  Include) erfolgreich
- Echte ~/.ssh/config parst read-only ohne Fehler (28 Hosts, 0 Warnungen, valide)
- `uv run sshcnfgr --help` und `generate --output` in neues Verzeichnis erfolgreich

### 8.2 Windows-Kompatibilitaet, Installer & Winget (erledigt 2026-11-28)

- Windows-Kompatibilitaet abgesichert:
  - `generator.py` quotiert `IdentityFile`-Pfade mit Leerzeichen (z. B. Windows-Benutzerprofile); `importer.py` entfernt Anfuehrungszeichen beim Import verlustfrei.
  - `importer.py`, `store.py` und `settings.py` lesen mit `utf-8-sig` (UTF-8-BOM-Toleranz).
  - `gui/__init__.py` setzt Windows `AppUserModelID` (`de.tbaer.sshcnfgr`) und bevorzugt `.ico` unter Windows.
  - `.github/workflows/ci.yml` fuehrt Qt6-GUI-Tests (Python 3.12/3.13) nun auch auf `windows-latest` aus.
- Windows-Installer (Option A) & Winget-Vorbereitung (Option C):
  - `packaging/windows/`: `generate_icons.py` (SVG -> PNG + Multi-Res-ICO via PySide6), Multi-EXE-Spec (`SSHCnfgr.exe` GUI + `sshcnfgr-cli.exe` CLI + `bin/sshcnfgr.cmd` Wrapper), Inno-Setup-Skript `sshcnfgr.iss` und `build_windows.ps1`.
  - `packaging/winget/generate_manifest.py`: erzeugt schema-validierte Winget-1.6.0-Manifeste fuer `ThomsBe.SSHCnfgr`.
  - `.github/workflows/windows-installer.yml`: automatischer Windows-Setup-Build, Silent-Install/Uninstall-Smoke-Test, Release-Upload und opt-in `publish-winget`-Job.
  - Dokumentation in `doc/windows-release.md` und `README.md` ergaenzt.

## 9. Offene Punkte (fachlich)

### Hoch

- Echte Match-Regeln (Match ...) werden noch nicht ausgewertet
- Kein dedizierter UI-Editor fuer extra_options je Host

### Mittel

- Eigene Gruppen-Ansicht mit Liste, Edit, Loeschen fehlt
- Effective-Identity/Effective-Agent pro Host koennte expliziter visualisiert werden
- Validierung fuer globale Optionen (z. B. Port als Zahl) nur begrenzt
- Loesch-Sicherheitsabfrage in der TUI fehlt (Pflichtenheft 5.1 verlangt sie)
- Exit-Codes sind nicht differenziert (Pflichtenheft 8 verlangt 2=Validierung, 3=Import)

### Niedrig

- Testsuite fehlt noch weitgehend (Import/Generator/Resolver als Unit-Tests)
- Backup-Strategie fuer Zieldateien ist im Pflichtenheft genannt, aber noch nicht als Feature umgesetzt
- Timestamp im Generator-Header verhindert Byte-identische Ausgabe; fuer Golden-Tests
  ggf. deterministisch oder abschaltbar machen
- `sshcnfgr import` ersetzt die komplette hosts.toml ohne Merge oder Warnung;
  mit Backup (siehe oben) waere das abgesichert

## 10. Offene Punkte (technisch)

- importer.py ist ein einfacher Zeilenparser; robustere Parsing-Strategie waere sinnvoll
- host.extra_options und global_options sind case-sensitive wie eingelesen,
  OpenSSH-Direktiven sind aber case-insensitive (betrifft z. B. resolve_identity_agent)
- Mehrfach vorkommende gleiche Direktiven (z. B. zwei Include-Zeilen) sind im
  Dict-Modell (extra_options/global_options) nicht abbildbar; letzter Wert gewinnt
- Feld-Herkunft (direkt, group, global, default) ist implizit, nicht als strukturierter Metadata-Layer modelliert

## 11. Priorisierte naechste Schritte

0. Erledigt 2026-07-28: Bugfix-Paket (Details siehe Abschnitt 8.1)

1. Pflichtenheft-Luecken schliessen
- Backup mit Zeitstempel vor jedem Ueberschreiben (Pflichtenheft 7), betrifft
  store.save_database und generator.write_generated_config
- Exit-Codes differenzieren: 2=Validierungsfehler, 3=Importfehler (Pflichtenheft 8)
- Loesch-Sicherheitsabfrage in der TUI (Pflichtenheft 5.1)

2. Tests einfuehren
- Unit-Tests fuer Importer und Resolver
- Golden-Tests fuer Generator (inkl. Host * Defaults am Dateiende)
- Dafuer Timestamp im Generator-Header deterministisch/abschaltbar machen
- Voraussetzung dafuer, die Parser-Erweiterungen aus Schritt 3 sicher zu machen

3. Match-Rule-MVP erweitern
- Mindestziel: Match host PATTERN fuer IdentityAgent/IdentityFile/Port
- Feld-Herkunft sauber markieren

4. TUI: Groups als erste Klasse
- Gruppenliste links oder eigener Screen
- Group create/edit/delete
- Group default settings sichtbarer machen

5. Host-Detail: Extra Options Editor
- einfache Key-Value Tabelle
- Mindestens IdentityAgent sichtbar/editierbar ohne TOML-Handarbeit

6. Release-Hygiene
- Changelog-Datei
- Pre-Release-Checkliste fuer PyPI in eigenem Dokument

## 12. Vorschlag fuer Arbeitsweise des naechsten Agenten

1. Erst Zielscope fuer den naechsten Schritt klar begrenzen
2. Beim Parser nur kleine sichere Inkremente
3. Nach jeder Aenderung mindestens einen Smoke-Test laufen lassen
4. Bei Datenmodell-Aenderungen immer store.py und generator.py mitziehen
5. README und ggf. doc/project.md mit aktualisieren

## 13. Nuetzliche Kommandos

- uv sync
- uv sync --extra dev
- uv run sshcnfgr --help
- uv run sshcnfgr import --source ~/.ssh/config
- uv run sshcnfgr identities scan
- uv run sshcnfgr generate --output ~/.config/sshcnfgr/config.generated
- uv run ruff check .
- uv run pytest
- uv run -m build
- uv run -m twine check dist/*

## 14. Bekannte Stolperfallen

- OpenSSH verwendet pro Parameter den ersten gefundenen Wert; Host * gehoert daher
  ans Dateiende, sonst schlagen globale Defaults die Host-Werte
- Include innerhalb eines Host-Blocks ist in OpenSSH konditional (nur bei Match
  aktiv) und gehoert nicht in globale Defaults
- fish-Heredoc in terminal automatisiert nicht robust; fuer Demo-Dateien lieber printf-basiert schreiben
- tomli-w serialisiert keine None-Werte; optionale Felder nur bei gesetztem Wert schreiben
- OpenSSH-Konfigurationen koennen komplex sein; aktuell nur Teilmenge bewusst unterstuetzt
