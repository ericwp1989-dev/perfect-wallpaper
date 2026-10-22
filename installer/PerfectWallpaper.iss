; Inno Setup script for Perfect Wallpaper. Built by scripts/build.py, which passes AppVersion.
; Installs for the current user only, so it needs no administrator rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Perfect Wallpaper"
#define AppExe "PerfectWallpaper.exe"

[Setup]
AppId={{7E2F2C6A-6B1D-4C0B-9C49-2D5B8E9A1F3E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Perfect Wallpaper contributors
AppPublisherURL=https://github.com/ericwp1989-dev/perfect-wallpaper
DefaultDirName={localappdata}\Programs\Perfect Wallpaper
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=PerfectWallpaper-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put an icon on the desktop"; Flags: unchecked
Name: "rightclick"; Description: "Add ""Make a perfect wallpaper"" to the right click menu for pictures"

[Files]
Source: "..\dist\PerfectWallpaper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\image\shell\PerfectWallpaper"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Make a perfect wallpaper"; Tasks: rightclick; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\image\shell\PerfectWallpaper"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: rightclick
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\image\shell\PerfectWallpaper\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: rightclick

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the right click entry may also have been added from the program's Options menu
Type: files; Name: "{app}\*.log"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\SystemFileAssociations\image\shell\PerfectWallpaper');
end;
