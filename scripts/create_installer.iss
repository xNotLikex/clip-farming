; Clip Farming Studio - Inno Setup Script
; Erstellt einen vollständigen, autarken Windows-Installer mit eingebetteter Python-Runtime & FFmpeg

#define MyAppName "Clip Farming Studio"
#define MyAppVersion "0.5.10"
#define MyAppPublisher "NotLike"
#define MyAppExeName "clip-farming.exe"

[Setup]
AppId={{8B1A2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={code:GetDefaultInstallDir}
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Clip-Farming-Installer
SetupIconFile=..\src-tauri\icons\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Haupt-Anwendung (Tauri GUI)
Source: "..\src-tauri\target\release\clip-farming.exe"; DestDir: "{app}"; DestName: "clip-farming.exe"; Flags: ignoreversion

; Standalone Python 3.12 Runtime & Module
Source: "..\dist\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

; FFmpeg & FFprobe Video-Engine
Source: "..\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; Python Backend Quellcode
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc,*.pyo"

; Benutzeroberfläche
Source: "..\ui\*"; DestDir: "{app}\ui"; Flags: ignoreversion recursesubdirs createallsubdirs

; Standardkonfiguration
Source: "..\config\config.yaml"; DestDir: "{app}\config"; Flags: ignoreversion onlyifdoesntexist

; Batch-Starter
Source: "..\SETUP.bat"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Dirs]
Name: "{app}\fonts"
Name: "{app}\downloads"
Name: "{app}\output\shorts"
Name: "{app}\output\metadata"
Name: "{app}\data\thumbnails"

[Registry]
Root: HKCU; Subkey: "Software\NotLike\Clip-Farming"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
; Automatische Hardware- und GPU-Optimierung nach der Installation
Filename: "{app}\runtime\python.exe"; Parameters: "-c ""import os; from src.video.gpu import get_best_video_encoder; print('Configuring GPU...'); enc = get_best_video_encoder(); print('Optimal encoder:', enc['name'])"""; WorkingDir: "{app}"; Flags: runhidden

; App nach Abschluss optional sofort starten
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function GetDefaultInstallDir(Param: String): String;
var
  PrevDir: String;
begin
  if RegQueryStringValue(HKCU, 'Software\NotLike\Clip-Farming', 'InstallPath', PrevDir) and (PrevDir <> '') and DirExists(PrevDir) then
  begin
    Result := PrevDir;
    Exit;
  end;
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B1A2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}_is1', 'InstallLocation', PrevDir) and (PrevDir <> '') and DirExists(PrevDir) then
  begin
    Result := PrevDir;
    Exit;
  end;
  Result := ExpandConstant('{localappdata}\Programs\Clip-Farming');
end;
