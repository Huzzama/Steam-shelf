; Steam Shelf installer (Inno Setup 6). tools/build.py runs this after PyInstaller:
;   ISCC /DAppVersion=0.8.0 /DSourceDir=dist\SteamShelf /DOutDir=dist tools\installer.iss
; Per-user install (no admin), like Steam Curator and the Grunge Editor.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\SteamShelf"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{7D1C5E6A-3B7F-4E2C-9B61-5A2F0C9D8E41}
AppName=Steam Shelf
AppVersion={#AppVersion}
AppVerName=Steam Shelf {#AppVersion}
AppPublisher=PimpMySteam
AppPublisherURL=https://pimpmysteam.com
AppSupportURL=https://pimpmysteam.com
DefaultDirName={localappdata}\Programs\SteamShelf
DefaultGroupName=Steam Shelf
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=SteamShelf-{#AppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\SteamShelf.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
; the agent has no window: stop it ourselves before files are replaced
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Steam Shelf"; Filename: "{app}\SteamShelf.exe"
Name: "{group}\Uninstall Steam Shelf"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Steam Shelf"; Filename: "{app}\SteamShelf.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SteamShelf.exe"; Description: "{cm:LaunchProgram,Steam Shelf}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM SteamShelf.exe"; Flags: runhidden; RunOnceId: "StopSteamShelf"

[Registry]
; the app itself writes HKCU\...\Run\SteamShelfAgent (Settings); the uninstaller removes it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SteamShelfAgent"; Flags: uninsdeletevalue

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  // the agent keeps running without a window: taskkill it so the files can be replaced
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM SteamShelf.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
