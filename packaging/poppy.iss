[Setup]
AppId={{4BF8B996-7A03-42B2-8C36-1376372CB04D}
AppName=Poppy
AppVersion={#Version}
AppPublisher=Poppy
AppPublisherURL=https://github.com/antaripnandi/poppy
DefaultDirName={localappdata}\Programs\Poppy
DefaultGroupName=Poppy
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
OutputDir={#OutputPath}
OutputBaseFilename=Poppy-Setup-{#Version}-x64
SetupIconFile={#IconPath}
UninstallDisplayIcon={app}\Poppy.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PayloadPath}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Poppy"; Filename: "{app}\Poppy.exe"
Name: "{autodesktop}\Poppy"; Filename: "{app}\Poppy.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Poppy.exe"; Description: "Launch Poppy"; Flags: postinstall nowait skipifsilent

[Code]
procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  RunKey, Command: String;
begin
  if Step = usUninstall then
  begin
    RunKey := 'Software\Microsoft\Windows\CurrentVersion\Run';
    if RegQueryStringValue(HKCU, RunKey, 'Poppy', Command) and
      (CompareText(Command, '"' + ExpandConstant('{app}\Poppy.exe') + '"') = 0) then
      RegDeleteValue(HKCU, RunKey, 'Poppy');
  end;
end;
