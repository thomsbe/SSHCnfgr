<#
.SYNOPSIS
Baut das Windows-Bundle (PyInstaller onedir) und den Inno-Setup-Installer fuer SSHCnfgr.

.DESCRIPTION
Spiegelt packaging/appimage/build_appimage.sh fuer Windows x64:
1. Erzeugt sshcnfgr.png und sshcnfgr.ico aus src/sshcnfgr/assets/sshcnfgr.svg
2. Bundelt SSHCnfgr.exe (Qt6-GUI) und sshcnfgr-cli.exe (CLI/TUI) gemeinsam mit PyInstaller
3. Fuehrt CLI-Smoke-Tests auf dem erzeugten Bundle aus
4. Kompiliert den Windows-Installer via Inno Setup (ISCC.exe), sofern nicht -SkipInstaller gesetzt ist
5. Erzeugt SHA256SUMS fuer das Setup-Artefakt
#>

[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $RootDir

try {
    $Version = (uv run --no-sync python -c "from sshcnfgr import __version__; print(__version__)").Trim()
    if (-not $Version) {
        throw "Version konnte nicht aus sshcnfgr.__version__ ermittelt werden."
    }

    Write-Host "==> Baue SSHCnfgr $Version fuer Windows (x64)"

    $BuildWinDir = Join-Path $RootDir "build\windows"
    $IconDir = Join-Path $BuildWinDir "icons"
    $PyInstDir = Join-Path $RootDir "build\pyinstaller-win"
    $DistDir = Join-Path $RootDir "dist"
    $BundleDir = Join-Path $PyInstDir "dist\SSHCnfgr"

    foreach ($dir in @($BuildWinDir, $PyInstDir)) {
        if (Test-Path $dir) {
            Remove-Item -Recurse -Force $dir
        }
    }
    New-Item -ItemType Directory -Force -Path $IconDir, $DistDir | Out-Null

    Write-Host "==> Erzeuge Windows-Icons (.png + .ico)..."
    $env:QT_QPA_PLATFORM = "offscreen"
    uv run --no-sync python (Join-Path $PSScriptRoot "generate_icons.py") `
        --svg (Join-Path $RootDir "src\sshcnfgr\assets\sshcnfgr.svg") `
        --out-dir $IconDir
    if ($LASTEXITCODE -ne 0) { throw "Icon-Erzeugung fehlgeschlagen." }

    Write-Host "==> Bundling mit PyInstaller (onedir: GUI + CLI)..."
    uv run --extra qt --with pyinstaller pyinstaller `
        --noconfirm `
        --clean `
        --distpath (Join-Path $PyInstDir "dist") `
        --workpath (Join-Path $PyInstDir "work") `
        (Join-Path $PSScriptRoot "sshcnfgr.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller-Build fehlgeschlagen." }

    $GuiExe = Join-Path $BundleDir "SSHCnfgr.exe"
    $CliExe = Join-Path $BundleDir "sshcnfgr-cli.exe"
    if (-not (Test-Path $GuiExe)) { throw "Erwartete GUI-Binary fehlt: $GuiExe" }
    if (-not (Test-Path $CliExe)) { throw "Erwartete CLI-Binary fehlt: $CliExe" }

    Write-Host "==> Smoke-Test auf dem PyInstaller-Bundle..."
    & $CliExe --version
    if ($LASTEXITCODE -ne 0) { throw "CLI-Smoke-Test (--version) fehlgeschlagen." }
    & $CliExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "CLI-Smoke-Test (--help) fehlgeschlagen." }

    if ($SkipInstaller) {
        Write-Host "==> -SkipInstaller gesetzt: PyInstaller-Bundle bereit unter $BundleDir"
        return
    }

    if (-not $IsccPath) {
        $cmd = Get-Command iscc -ErrorAction SilentlyContinue
        if ($cmd) {
            $IsccPath = $cmd.Source
        } else {
            $candidates = @(
                "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
                "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
            )
            foreach ($cand in $candidates) {
                if ($cand -and (Test-Path $cand)) {
                    $IsccPath = $cand
                    break
                }
            }
        }
    }

    if (-not $IsccPath -or -not (Test-Path $IsccPath)) {
        throw "Inno Setup (ISCC.exe) nicht gefunden. Installiere z. B. per: winget install JRSoftware.InnoSetup (oder nutze -SkipInstaller)."
    }

    Write-Host "==> Erzeuge Inno-Setup-Installer mit $IsccPath..."
    & $IsccPath "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot "sshcnfgr.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno-Setup-Kompilierung fehlgeschlagen." }

    $SetupName = "SSHCnfgr-$Version-x64-setup.exe"
    $SetupPath = Join-Path $DistDir $SetupName
    if (-not (Test-Path $SetupPath)) { throw "Erwarteter Installer fehlt: $SetupPath" }

    $Hash = (Get-FileHash -Algorithm SHA256 -Path $SetupPath).Hash.ToLowerInvariant()
    $ShaFile = Join-Path $DistDir "SSHCnfgr-$Version-x64-setup.SHA256SUMS.txt"
    "$Hash  $SetupName" | Set-Content -Encoding ascii -NoNewline -Path $ShaFile
    "`n" | Add-Content -Encoding ascii -NoNewline -Path $ShaFile

    Write-Host "==> Fertig:"
    Get-Item $SetupPath, $ShaFile | Format-Table Name, Length, LastWriteTime -AutoSize
}
finally {
    Pop-Location
}
