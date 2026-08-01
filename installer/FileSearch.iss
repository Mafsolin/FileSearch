#define AppName "FileSearch"
#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif
#if Ver < EncodeVer(6, 3, 0)
  #error FileSearch requires Inno Setup 6.3.0 or later
#endif

[Setup]
AppId={{B26AF219-A6F3-4D8F-BB03-447F11098539}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=FileSearch
AppPublisherURL=https://github.com/Mafsolin/FileSearch
AppSupportURL=https://github.com/Mafsolin/FileSearch/issues
AppUpdatesURL=https://github.com/Mafsolin/FileSearch/releases
DefaultDirName={autopf}\FileSearch
DefaultGroupName=FileSearch
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=FileSearch-Setup-{#AppVersion}
SetupIconFile=..\assets\brand\filesearch.ico
UninstallDisplayName=FileSearch
UninstallDisplayIcon={app}\app\FileSearch.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName=FileSearch
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription=FileSearch installer

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\app\*"

[Files]
Source: "..\dist\FileSearch\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FileSearch"; Filename: "{app}\app\FileSearch.exe"; WorkingDir: "{app}\app"
Name: "{autodesktop}\FileSearch"; Filename: "{app}\app\FileSearch.exe"; WorkingDir: "{app}\app"; Tasks: desktopicon

[Run]
Filename: "{app}\app\FileSearch.exe"; Description: "Запустить FileSearch"; Flags: nowait postinstall skipifsilent
