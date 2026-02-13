#define MyAppName "Switchology Cockpit Companion"
#define MyAppPublisher "Switchology"
#define MyAppExeName "Companion App.cmd"


[Setup]
AppId={{ed7b8649-5957-4d1b-b4ca-c25769571bc8}}  ; needs to stay constant across versions
AppName={#MyAppName}
AppVersion={#gitrev}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppPublisher}\{#MyAppName}

DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes

; Only allow the installer to run on x64-compatible systems,
; and enable 64-bit install mode.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

UsePreviousAppDir=yes
UsePreviousGroup=yes

CloseApplications=yes
RestartApplications=no

OutputDir={#srcdir}\..
OutputBaseFilename=Companion_Setup_{#gitrev}

[Files]
Source: "{#srcdir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs


[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{cmd}"; Parameters: "/c ""{app}\Companion App.cmd"""; WorkingDir: "{app}"; IconFilename: "{app}\res\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{cmd}"; Parameters: "/c ""{app}\Companion App.cmd"""; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\res\icon.ico"

[Run]
Filename: "{app}\Readme.md"; Description: "View the README file"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent