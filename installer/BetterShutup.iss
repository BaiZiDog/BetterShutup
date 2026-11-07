; BetterShutup installer for Inno Setup 6.
; Build with: python tools/build_installer.py

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#ifndef AppFileVersion
  #define AppFileVersion "1.0.1.0"
#endif

#define AppName "BetterShutup"
#define AppPublisher "BaiZiDog"
#define AppURL "https://github.com/BaiZiDog/BetterShutup"

[Setup]
AppId={{f705ffa8-32ba-491d-9b95-2d9aa602c3d5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppFileVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppFileVersion}
DefaultDirName={localappdata}\Programs\BetterShutup
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=BetterShutup-{#AppVersion}-setup
SetupIconFile=..\better_shutup\assets\BetterShutup.ico
UninstallDisplayIcon={app}\BetterShutup.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\BetterShutup.exe"; DestDir: "{app}"; DestName: "BetterShutup.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; DestName: "NOTICE.txt"; Flags: ignoreversion

[Dirs]
; Keep user data across upgrades and uninstalls.
Name: "{localappdata}\BetterShutup"; Flags: uninsneveruninstall
Name: "{localappdata}\BetterShutup\sounds"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BetterShutup.exe"
Name: "{group}\{#AppName} 数据目录"; Filename: "{localappdata}\BetterShutup"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\BetterShutup.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BetterShutup.exe"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
