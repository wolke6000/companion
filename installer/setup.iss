#define MyAppName "Switchology Cockpit Companion"
#define MyAppPublisher "Switchology e.U."
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
RestartApplications=yes

AppMutex=SwitchologyAppMutex

OutputDir={#srcdir}\..
OutputBaseFilename=Companion_Setup_{#gitrev}

[Files]
Source: "{#srcdir}\*"; DestDir: "{app}"; Flags: recursesubdirs


[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon