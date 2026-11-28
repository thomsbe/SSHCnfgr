# Windows-Installer (Inno Setup) & Winget-Release

Dieses Dokument beschreibt den Build des Windows-Installers (Option A) sowie die Veroeffentlichung und automatische Aktualisierung ueber den Windows Package Manager **Winget** (Option C).

## Architektur des Windows-Bundles

Unter Windows unterscheidet das PE-Format zwischen GUI-Subsystem (kein Konsolenfenster) und Konsolen-Subsystem (Terminal-Ausgabe). Deshalb erzeugt [sshcnfgr.spec](../packaging/windows/sshcnfgr.spec) ein gemeinsames `--onedir`-Bundle mit geteiltem `_internal`-Verzeichnis (Python + PySide6/Qt6 + Textual):

- `SSHCnfgr.exe` — Windows-GUI-Subsystem (Startmenue / Desktop, kein schwarzes Konsolenfenster)
- `sshcnfgr-cli.exe` — Konsolen-Subsystem fuer CLI und TUI
- `bin/sshcnfgr.cmd` — duenner Wrapper, der `sshcnfgr-cli.exe` aufruft; nur `{app}\bin` wird in den `PATH` aufgenommen, damit `sshcnfgr` im Terminal nicht mit `SSHCnfgr.exe` kollidiert.

## Lokaler Build unter Windows

Voraussetzungen:
- `uv` und Python 3.12+ (`uv sync --extra qt`)
- Fuer den fertigen `.exe`-Installer zusaetzlich **Inno Setup 6**:
  ```powershell
  winget install JRSoftware.InnoSetup
  ```

Build ausfuehren:

```powershell
# Nur PyInstaller-Bundle + Icons + Smoke-Tests (ohne Inno Setup):
.\packaging\windows\build_windows.ps1 -SkipInstaller

# Komplettes Setup (dist\SSHCnfgr-<version>-x64-setup.exe + SHA256SUMS):
.\packaging\windows\build_windows.ps1
```

## Automatischer Release-Build (GitHub Actions)

Der Workflow [.github/workflows/windows-installer.yml](../.github/workflows/windows-installer.yml) laeuft bei jedem veroeffentlichten GitHub Release (oder manuell per `workflow_dispatch`):

1. Erzeugt `.png`/`.ico` aus `src/sshcnfgr/assets/sshcnfgr.svg`.
2. Bundelt GUI + CLI mit PyInstaller und baut `SSHCnfgr-<version>-x64-setup.exe` per Inno Setup.
3. Fuehrt einen automatischen Silent-Install-/Smoke-/Uninstall-Test auf `windows-latest` durch.
4. Laedt `SSHCnfgr-<version>-x64-setup.exe` und `SSHCnfgr-<version>-x64-setup.SHA256SUMS.txt` direkt an das GitHub Release hoch und erzeugt das passende Winget-Manifest als Build-Artefakt.

## Winget-Einrichtung (`ThomsBe.SSHCnfgr`)

### 1. Erstmalige Einreichung bei `microsoft/winget-pkgs`

Vor der Automatisierung muss das Paket einmalig in `microsoft/winget-pkgs` aufgenommen werden:

1. Ein GitHub Release (z. B. `v1.1.0`) mit hochgeladener `SSHCnfgr-1.1.0-x64-setup.exe` erstellen.
2. Das vom Workflow erzeugte Artefakt `dist/winget/manifests/t/ThomsBe/SSHCnfgr/<version>/` herunterladen (oder lokal erzeugen):
   ```powershell
   uv run python packaging/winget/generate_manifest.py `
     --version 1.1.0 `
     --sha256 <SHA256_AUS_SHA256SUMS> `
     --out-dir dist\winget\manifests\t\ThomsBe\SSHCnfgr\1.1.0
   ```
3. Manifest lokal gegen das offizielle Winget-Schema validieren:
   ```powershell
   winget validate --manifest dist\winget\manifests\t\ThomsBe\SSHCnfgr\1.1.0
   ```
4. Per `wingetcreate submit` (oder PR im Fork von `microsoft/winget-pkgs`) einreichen:
   ```powershell
   winget install Microsoft.WingetCreate
   wingetcreate submit dist\winget\manifests\t\ThomsBe\SSHCnfgr\1.1.0
   ```

### 2. Automatische Updates fuer alle Folge-Releases

Sobald der erste PR in `microsoft/winget-pkgs` gemerged ist:

1. In den GitHub Repository Settings → *Secrets and variables → Actions*:
   - **Secret** `WINGET_TOKEN`: Personal Access Token (Classic mit `public_repo`-Scope) anlegen.
   - **Variable** `ENABLE_WINGET_PUBLISH`: auf `true` setzen.
2. Ab dem naechsten GitHub Release oeffnet der Job `publish-winget` automatisch einen Update-PR in `microsoft/winget-pkgs`.
3. Nutzer installieren und aktualisieren anschliessend per:
   ```powershell
   winget install ThomsBe.SSHCnfgr
   winget upgrade ThomsBe.SSHCnfgr
   ```
