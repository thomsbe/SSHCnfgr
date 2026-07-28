# Projektidee

Ich möchte eine TUI (Terminal User Interface) mit Python bauen, was die ssh-config (Keys, vor allem die Hosts) verwaltet. Also alle Host auflisten, neue anlegen, Namen ändern, Key Zuordnung usw. Ich denke, ein Toml-File als Basis, was in .config/sshcnfgr steht als Basis ist gut. Daraus genereiert man sich die ssh-config, damit kann man Einträge auch deaktivieren, also zwar in der Konfig-Datenbank, aber nicht in der Konfig.

Benutze ein aktuelles TUI Framework, wenn es mit Maus zu bedienen geht, gut.

Ein Import einer vorhandenen Config ist cool.

Python mit 'uv' verwalten. Am Ende soll man mit 'uv tool install' das Ding installieren können.

## Pflichtenheft

### 1. Zweck und Ziel

Das Projekt SSHCnfgr ist ein Python-Tool mit Terminal User Interface zur Verwaltung von SSH-Hosteintraegen.

Ziele:

- SSH-Hosts komfortabel anlegen, bearbeiten, deaktivieren und loeschen
- Eine interne, versionierbare Konfigurationsdatenbank in TOML nutzen
- Daraus eine gueltige OpenSSH-Config generieren
- Eine bestehende OpenSSH-Config importieren koennen
- Installation und Ausfuehrung ueber uv ermoeglichen

### 2. Projektumfang

Im Umfang enthalten:

- Interaktive TUI zur Hostverwaltung
- Persistenz in einer TOML-Datei unter ~/.config/sshcnfgr
- Generator fuer OpenSSH-Config
- Importfunktion einer bestehenden SSH-Config
- CLI-Einstieg fuer Import und Generierung ohne TUI

Nicht im ersten Umfang enthalten:

- Vollstaendige Abbildung aller exotischen OpenSSH-Sonderfaelle (z. B. komplexe Match-Bloecke)
- Verwaltung von entfernten Schluesseldateien
- Agent- oder Keychain-Integrationen

### 3. Technische Randbedingungen

- Programmiersprache: Python 3.12+
- Paket- und Umgebungsverwaltung: uv
- Installierbar als Tool via uv tool install
- TUI-Framework: Textual (oder gleichwertig modern mit Mausunterstuetzung)
- Zielplattform: Linux (primaer), mit moeglicher Portabilitaet auf macOS

### 4. Datenhaltung

#### 4.1 Speicherort

- Basisverzeichnis: ~/.config/sshcnfgr
- Datenbankdatei: ~/.config/sshcnfgr/hosts.toml
- Generierte SSH-Config: ~/.config/sshcnfgr/config.generated

#### 4.2 Datenmodell (MVP)

Jeder Hosteintrag enthaelt mindestens:

- id (stabile interne ID, UUID)
- name (Alias, entspricht Host)
- enabled (bool)
- host_name (entspricht HostName)
- user (optional)
- port (optional)
- identity_file (Pfad, optional)
- tags (Liste optional)
- extra_options (Key-Value fuer weitere SSH-Optionen)

Validierungsregeln:

- name ist eindeutig
- name darf keine Leerzeichen enthalten
- port muss im Bereich 1-65535 liegen
- identity_file darf leer sein, sonst muss ein valider Pfadstring vorliegen

### 5. Funktionale Anforderungen

#### 5.1 TUI-Funktionen

Pflichtfunktionen:

- Liste aller Hosts anzeigen
- Suche/Filter nach Name oder Tag
- Host anlegen
- Host bearbeiten (inkl. Name aendern)
- Host aktivieren/deaktivieren
- Host loeschen (mit Sicherheitsabfrage)
- Speichern der TOML-Datenbank
- Generierung der SSH-Config anstossen

Sollfunktionen:

- Mausbedienung fuer Auswahl, Buttons, Eingabefelder
- Tastaturkuerzel fuer zentrale Aktionen

#### 5.2 Importfunktion

- Einlesen einer vorhandenen SSH-Config (Default: ~/.ssh/config)
- Uebernahme von Standard-Hostbloecken in das interne Datenmodell
- Nicht eindeutig zuordenbare Direktiven werden in extra_options abgelegt oder protokolliert
- Konflikte bei doppelten Hostnamen werden aufgeloest durch:
	- Suffix-Vergabe (-1, -2, ...)
	- Protokolleintrag im Import-Report

#### 5.3 Generierung der SSH-Config

- Nur enabled=true Hosts werden ausgegeben
- Deterministische Reihenfolge (alphabetisch nach name)
- Ausgabe enthaelt je Host einen Host-Block mit den gesetzten Optionen
- Leere/ungueltige Felder werden nicht geschrieben

### 6. CLI-Anforderungen

Es muss ein CLI-Einstiegspunkt sshcnfgr vorhanden sein.

Pflichtkommandos:

- sshcnfgr tui
- sshcnfgr import --source ~/.ssh/config
- sshcnfgr generate --output ~/.config/sshcnfgr/config.generated

Optional in spaeteren Ausbaustufen:

- sshcnfgr validate
- sshcnfgr export --active-only

### 7. Sicherheits- und Stabilitaetsanforderungen

- Vor jedem Ueberschreiben einer Zieldatei wird ein Backup mit Zeitstempel erstellt
- Schreiboperationen erfolgen atomar (temp-file + replace)
- Berechtigungen sensibler Dateien werden respektiert
- Es werden keine privaten Schluesselinhalte eingelesen oder gespeichert, nur Dateipfade

### 8. Logging und Fehlermanagement

- Nutzerfreundliche Fehlermeldungen in TUI und CLI
- Import-Report mit Anzahl uebernommener Hosts, Konflikten, Warnungen
- Exit-Codes fuer CLI:
	- 0 Erfolg
	- 1 Allgemeiner Fehler
	- 2 Validierungsfehler
	- 3 Importfehler

### 9. Qualitaetssicherung

Tests (MVP):

- Unit-Tests fuer Parser, Validierung, Generator
- Golden-File-Tests fuer generierte SSH-Config
- Mindestens ein Integrations-Test fuer Import -> Speichern -> Generieren

Qualitaetskriterien:

- Reproduzierbare Ausgabe bei gleichen Eingabedaten
- Keine Datenverluste bei wiederholtem Laden/Speichern

### 10. Projektstruktur (Soll)

- src/sshcnfgr/app.py (TUI Start)
- src/sshcnfgr/cli.py (CLI Kommandos)
- src/sshcnfgr/model.py (Datenmodell)
- src/sshcnfgr/store.py (TOML IO)
- src/sshcnfgr/importer.py (SSH-Import)
- src/sshcnfgr/generator.py (SSH-Config Ausgabe)
- tests/...

### 11. Build, Packaging und Distribution

- Projektkonfiguration in pyproject.toml
- Skript-Einstiegspunkt fuer sshcnfgr
- Installation via:
	- uv tool install .

### 12. Abnahmekriterien

Das MVP gilt als abgenommen, wenn folgende Punkte erfuellt sind:

- Der Nutzer kann in der TUI Hosts erstellen, bearbeiten, deaktivieren und loeschen
- Die Daten werden korrekt in ~/.config/sshcnfgr/hosts.toml gespeichert
- Eine vorhandene ~/.ssh/config kann importiert werden
- Die Generierung einer gueltigen config.generated funktioniert
- Deaktivierte Hosts erscheinen nicht in der generierten Datei
- Das Tool laesst sich lokal per uv tool install . installieren und starten