#define AppName "mini Teto"
#define AppVersion "1.0.0"

[Setup]
AppId={{B5F1B0F2-5C4C-4C79-9A4E-6D1E5F3A7C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=mini Teto
DefaultDirName={autopf}\mini Teto
DefaultGroupName=mini Teto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=mini-teto-setup
SetupIconFile=mini-teto.ico
UninstallDisplayIcon={app}\mini-teto.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
english.AutoStart=Start mini Teto when I sign in to Windows
russian.AutoStart=Запускать mini Teto при входе в Windows
english.LaunchNow=Start mini Teto now
russian.LaunchNow=Запустить mini Teto сейчас

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\mini-teto.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\mini Teto"; Filename: "{app}\mini-teto.exe"
Name: "{autodesktop}\mini Teto"; Filename: "{app}\mini-teto.exe"; Tasks: desktopicon
Name: "{userstartup}\mini Teto"; Filename: "{app}\mini-teto.exe"; Tasks: autostart

[Run]
Filename: "{app}\mini-teto.exe"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\mini-teto.exe"; Parameters: "quit"; Flags: runhidden; RunOnceId: "QuitTeto"
