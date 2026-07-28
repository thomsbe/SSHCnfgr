# AGENTS.md

Diese Datei beschreibt, wie LLMs/Agenten in diesem Repository arbeiten sollen.

## Projektkontext

SSHCnfgr ist ein kleines Demo- und Lernprojekt fuer Python-TUIs.
Ziel ist, SSH-Hosts, Gruppen und Identities ueber eine Textual-TUI und Click-CLI zu verwalten.

## Wichtige Doku

- Produktidee und Pflichtenheft: doc/project.md
- Einstieg und Nutzung: README.md

## Technischer Stack

- Python 3.12+
- uv fuer Environment und Paketmanagement
- Textual fuer TUI
- Click fuer CLI
- Loguru fuer Logging
- TOML als Source of Truth

## Source-Struktur

- src/sshcnfgr/cli.py: Click-CLI und Kommandos
- src/sshcnfgr/tui.py: Textual-App
- src/sshcnfgr/model.py: Datenmodell (Hosts, Groups, Identities)
- src/sshcnfgr/store.py: TOML Load/Save
- src/sshcnfgr/importer.py: SSH-Config Import
- src/sshcnfgr/generator.py: OpenSSH-Config Erzeugung
- src/sshcnfgr/identities.py: Identity Discovery aus ~/.ssh

## Lauf- und Testkommandos

- Abhaengigkeiten installieren: uv sync
- CLI Help: uv run sshcnfgr --help
- TUI starten: uv run sshcnfgr tui
- Import: uv run sshcnfgr import --source ~/.ssh/config
- Generate: uv run sshcnfgr generate --output ~/.config/sshcnfgr/config.generated
- Identities scannen: uv run sshcnfgr identities scan

## Architekturprinzipien

- hosts.toml ist die Source of Truth
- generierte SSH-Config ist ein Artefakt
- keine privaten Schluesselinhalte speichern, nur Metadaten/Pfade
- Aenderungen moeglichst rueckwaertskompatibel halten

## Agenten-Richtlinien fuer Codeaenderungen

- Kleine, zielgerichtete Aenderungen statt grosser Refactors
- Vorhandene CLI-Kommandos und Dateistruktur nicht ohne Grund brechen
- Bei Datenmodell-Aenderungen immer Load/Save in store.py mitpflegen
- Bei Identitaets-Aenderungen auch Resolver-Logik in generator.py pruefen
- Nach Aenderungen mindestens einen Smoke-Test via uv run sshcnfgr --help oder generate ausfuehren

## Priorisierte naechste Themen

- Gruppenverwaltung als eigene TUI-Ansicht
- Effective-Identity Anzeige je Host
- Tests fuer Import/Generator/Resolver
