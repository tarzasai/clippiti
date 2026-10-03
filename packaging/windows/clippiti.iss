; Inno Setup script for clippiti. Compiled in CI on the windows runner:
;   ISCC /DMyAppVersion=<version> packaging\windows\clippiti.iss
; Expects the PyInstaller onedir output in dist\clippiti\.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Clippiti"
#define MyAppExeName "clippiti.exe"

[Setup]
AppId={{B2D6F3A1-4C9E-4E2B-9E4A-CL1PP1T1PLAY}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Tarzasai
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=clippiti-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "dist\clippiti\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
