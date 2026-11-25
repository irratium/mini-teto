#define AppName "mini Teto"
#define AppVersion "1.1.0"

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
english.Fonts=Download fonts (Fredoka, Nunito, Noto Sans JP): her look and Japanese letters
russian.Fonts=Скачать шрифты (Fredoka, Nunito, Noto Sans JP): внешний вид и японские буквы
english.FontsTitle=Downloading fonts
russian.FontsTitle=Загрузка шрифтов
english.FontsDesc=Optional: if there is no internet, mini Teto uses the fonts Windows already has.
russian.FontsDesc=Необязательно: без интернета mini Teto возьмёт шрифты, которые уже есть в Windows.

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "fonts"; Description: "{cm:Fonts}"

[Files]
Source: "..\dist\mini-teto.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{tmp}\Fredoka.ttf"; DestDir: "{app}\fonts"; Flags: external ignoreversion skipifsourcedoesntexist; Tasks: fonts
Source: "{tmp}\Nunito.ttf"; DestDir: "{app}\fonts"; Flags: external ignoreversion skipifsourcedoesntexist; Tasks: fonts
Source: "{tmp}\NotoSansJP.ttf"; DestDir: "{app}\fonts"; Flags: external ignoreversion skipifsourcedoesntexist; Tasks: fonts

[Icons]
Name: "{autoprograms}\mini Teto"; Filename: "{app}\mini-teto.exe"
Name: "{autodesktop}\mini Teto"; Filename: "{app}\mini-teto.exe"; Tasks: desktopicon
Name: "{userstartup}\mini Teto"; Filename: "{app}\mini-teto.exe"; Tasks: autostart

[Run]
Filename: "{app}\mini-teto.exe"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\mini-teto.exe"; Parameters: "quit"; Flags: runhidden; RunOnceId: "QuitTeto"

[Code]
var
  FontPage: TDownloadWizardPage;

procedure InitializeWizard;
begin
  FontPage := CreateDownloadPage(CustomMessage('FontsTitle'), CustomMessage('FontsDesc'), nil);
end;

{ One font. A failed download (no internet, a moved link) is fine: fonts are optional. Only Cancel stops setup. }
function GetFont(const Url, FileName: String): Boolean;
begin
  Result := True;
  FontPage.Clear;
  FontPage.Add(Url, FileName, '');
  try
    FontPage.Download;
  except
    if FontPage.AbortedByUser then
      Result := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('fonts') then
  begin
    FontPage.Show;
    try
      if Result then Result := GetFont('https://github.com/google/fonts/raw/main/ofl/fredoka/Fredoka%5Bwdth%2Cwght%5D.ttf', 'Fredoka.ttf');
      if Result then Result := GetFont('https://github.com/google/fonts/raw/main/ofl/nunito/Nunito%5Bwght%5D.ttf', 'Nunito.ttf');
      if Result then Result := GetFont('https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf', 'NotoSansJP.ttf');
    finally
      FontPage.Hide;
    end;
  end;
end;
