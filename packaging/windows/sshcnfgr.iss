; Inno Setup 6 Skript fuer SSHCnfgr (Windows x64)
; Baut einen Windows-Installer (ohne Admin-Zwang, optional systemweit & Winget-tauglich).

#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif

#define MyAppName "SSHCnfgr"
#define MyAppPublisher "Thomas Baer"
#define MyAppURL "https://github.com/thomsbe/SSHCnfgr"
#define MyAppGuiExe "SSHCnfgr.exe"
#define MyAppCliExe "sshcnfgr-cli.exe"
#define MySourceDir "..\..\build\pyinstaller-win\dist\SSHCnfgr"
#define MyIconFile "..\..\build\windows\icons\sshcnfgr.ico"

[Setup]
; Stabile GUID fuer saubere In-Place-Upgrades und Winget-Erkennung.
AppId={{8E6A5B2C-4F1D-4C9A-9D3B-7A6E5C1B2D4E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=SSHCnfgr-{#MyAppVersion}-x64-setup
SetupIconFile={#MyIconFile}
UninstallDisplayIcon={app}\{#MyAppGuiExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "CLI/TUI (sshcnfgr) zum PATH hinzufuegen"; GroupDescription: "Systemintegration:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "sshcnfgr.cmd"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppGuiExe}"; Comment: "OpenSSH-Hosts, Gruppen und Identities verwalten"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppGuiExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppGuiExe}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function GetPathRootKey(): Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function GetPathSubKey(): String;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

procedure EnvAddPath(DirToAdd: String);
var
  Paths: String;
  CheckPath: String;
begin
  if not RegQueryStringValue(GetPathRootKey(), GetPathSubKey(), 'Path', Paths) then
    Paths := '';

  CheckPath := ';' + UpperCase(Paths) + ';';
  if Pos(';' + UpperCase(DirToAdd) + ';', CheckPath) > 0 then
    exit;

  if (Length(Paths) > 0) and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + DirToAdd;

  RegWriteExpandStringValue(GetPathRootKey(), GetPathSubKey(), 'Path', Paths);
end;

procedure EnvRemovePath(DirToRemove: String);
var
  Paths: String;
  P: Integer;
  NewPaths: String;
  Token: String;
begin
  if not RegQueryStringValue(GetPathRootKey(), GetPathSubKey(), 'Path', Paths) then
    exit;

  NewPaths := '';
  while Length(Paths) > 0 do
  begin
    P := Pos(';', Paths);
    if P > 0 then
    begin
      Token := Copy(Paths, 1, P - 1);
      Delete(Paths, 1, P);
    end
    else
    begin
      Token := Paths;
      Paths := '';
    end;

    if (Length(Token) > 0) and (CompareText(Token, DirToRemove) <> 0) then
    begin
      if Length(NewPaths) > 0 then
        NewPaths := NewPaths + ';';
      NewPaths := NewPaths + Token;
    end;
  end;

  RegWriteExpandStringValue(GetPathRootKey(), GetPathSubKey(), 'Path', NewPaths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}\bin'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    EnvRemovePath(ExpandConstant('{app}\bin'));
end;
