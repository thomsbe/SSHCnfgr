# SSHCnfgr

SSHCnfgr ist mein persoenliches Demo- und Lernprojekt fuer Python-TUIs.

Das Projekt zeigt, wie man mit Textual, Click und Loguru ein echtes, aber ueberschaubares Tool baut:

- SSH-Hosts, Gruppen und Identities in einer TOML-Datenbasis verwalten
- daraus eine OpenSSH-Config generieren
- bestehende SSH-Configs importieren

Ziel ist nicht, ein Produkt fuer jedermann zu bauen, sondern neue Dinge in Python/TUI zu lernen.
Wenn dabei ein kleines nuetzliches Tool herauskommt: super. Wenn nicht: auch okay.

## Arbeitsweise

- AI-assisted Code ist hier explizit Teil des Plans.
- Ich lasse mir von KI erklaeren, was passiert, und nachvollziehe die Schritte selbst.
- Der Code wird bewusst geprueft und verstanden.
- Es ist nicht "vibe coded".

## Status

Aktueller Stand ist ein fruehes, lauffaehiges MVP mit Fokus auf Lernbarkeit und klarer Architektur.

- Aktuelle Paketversion: 0.1.0a1 (Alpha)

## Warum diese Architektur?

- TOML ist die Source of Truth
- Die generierte SSH-Config ist ein Build-Artefakt
- Deaktivierte Hosts bleiben in der Datenbank, landen aber nicht in der generierten Datei

## Doku im Repo

- Produktidee und Pflichtenheft: doc/project.md
- Hinweise fuer LLMs/Agenten: AGENTS.md

## uv auf Linux installieren

Empfohlener Weg (offizieller Installer):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Alternative mit wget:

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
```

Danach Verfuegbarkeit pruefen:

```bash
uv --version
```

Wenn uv nach der Installation nicht gefunden wird, eine neue Shell oeffnen oder die Shell-Config neu laden.

## Quickstart mit uv

```bash
uv sync
uv run sshcnfgr --help
uv run sshcnfgr tui
```

## Installation als Tool

```bash
uv tool install .
sshcnfgr --help
```

## Nutzung unter Linux (aktueller Stand)

Fuer Anwender, die den aktuellen MVP ausprobieren wollen:

1. uv installieren (siehe oben)
2. Projekt klonen
3. Im Projektverzeichnis ausfuehren:

```bash
uv sync
uv run sshcnfgr --help
uv run sshcnfgr tui
```

Optional mit bestehender SSH-Config starten:

```bash
uv run sshcnfgr import --source ~/.ssh/config
uv run sshcnfgr identities scan
uv run sshcnfgr generate --output ~/.config/sshcnfgr/config.generated
```

Hinweise:

- Source of Truth ist ~/.config/sshcnfgr/hosts.toml
- Generierte Datei ist ~/.config/sshcnfgr/config.generated
- Private Keys werden nicht gespeichert, nur Pfade und Metadaten

## Entwicklung unter Linux

Fuer Developer, die das Projekt erweitern wollen:

```bash
uv sync --extra dev
uv run sshcnfgr --help
```

Nutzliche Befehle:

```bash
uv run ruff check .
uv run pytest
```

Packaging/Release lokal pruefen:

```bash
uv run -m build
uv run -m twine check dist/*
```

## License

MIT, siehe LICENCE.

## Release Notizen (PyPI)

Fuer Vorab-Releases (Alpha/Beta) wird PEP 440 genutzt:

- Alpha: 0.1.0a1, 0.1.0a2, ...
- Beta: 0.1.0b1, 0.1.0b2, ...
- Stable: 0.1.0

Typischer Ablauf:

1. Version in pyproject.toml anheben
2. Pakete bauen mit uv run -m build
3. Upload mit uv run -m twine upload dist/*

## Wichtige Dateien

- `~/.config/sshcnfgr/hosts.toml` Datenbank
- `~/.config/sshcnfgr/config.generated` generierte OpenSSH-Config
- `~/.config/sshcnfgr/sshcnfgr.log` Logdatei

## CLI Beispiele

```bash
# Vorhandene SSH-Config importieren
uv run sshcnfgr import --source ~/.ssh/config

# SSH-Config aus TOML generieren
uv run sshcnfgr generate --output ~/.config/sshcnfgr/config.generated

# Identities aus ~/.ssh erfassen
uv run sshcnfgr identities scan

# Bekannte Identities anzeigen
uv run sshcnfgr identities list

# Gruppen-Default-Identity setzen
uv run sshcnfgr groups set-identity prod id_ed25519

# TUI starten
uv run sshcnfgr tui
```

## TUI Lern-Hinweise

- Die Hostliste links wird aus der TOML geladen.
- Die Identity-Liste zeigt verwaltete Schluesselprofile.
- "Scan ~/.ssh" liest lokale Key-Dateien mit .pub-Pendant ein.
- "Use Selected" uebernimmt die gewaehlte Identity ins Host-Formular.
- Mit einem Klick auf einen Host werden Felder rechts befuellt.
- Speichern schreibt nur die TOML-Datenbank.
- Generate erstellt die SSH-Ausgabedatei aus allen aktiven Hosts.

## TOML Features (Basis)

`hosts.toml` ist die Source of Truth. Aktuell unterstuetzt sie:

- `groups`: Definierte Host-Gruppen (Name + optionale Beschreibung)
- `identities`: Definierte Identity-Profile (Name, IdentityFile, Quelle)
- `hosts`: Hosteintraege mit Feldern wie name, host_name, user, port, identity_file
- `enabled`: Aktive/inaktive Hosts
- `groups` pro Host: Mehrfachzuordnung via Liste
- `identity` pro Host: Referenz auf ein Identity-Profil
- `identity` pro Gruppe: Gruppen-Default-Identity
- `extra_options`: Freie SSH-Direktiven als Key/Value

Beispiel:

```toml
[[groups]]
name = "prod"
description = "Produktivsysteme"
identity = "id_ed25519"

[[groups]]
name = "lab"

[[hosts]]
id = "a8f01f2e-5d3f-4f9f-a6aa-222d5ed42f30"
name = "web-prod"
enabled = true
host_name = "10.0.0.12"
user = "ubuntu"
port = 22
identity = "id_ed25519"
groups = ["prod"]
tags = ["k8s"]

[[identities]]
name = "id_ed25519"
identity_file = "/home/thomas/.ssh/id_ed25519"
source = "local-ssh"
public_key_file = "/home/thomas/.ssh/id_ed25519.pub"
public_key_preview = "ssh-ed25519 thomas@workstation"
enabled = true

[hosts.extra_options]
ServerAliveInterval = "30"
StrictHostKeyChecking = "accept-new"
```
