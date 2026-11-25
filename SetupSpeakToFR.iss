[Setup]
AppName=SpeakToFR
AppVersion=1.0.0
AppPublisher=SpeakToFR
DefaultDirName={pf32}\SpeakToFR
DefaultGroupName=SpeakToFR
DisableProgramGroupPage=yes
OutputBaseFilename=SetupSpeakToFR
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\SpeakToFR.exe
PrivilegesRequired=admin
CloseApplications=yes
CloseApplicationsFilter=SpeakToFR.exe
AppMutex=SpeakToFR.Singleton

[Files]
Source: "dist\SpeakToFR.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "help.html"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SpeakToFR"; Filename: "{app}\SpeakToFR.exe"
Name: "{group}\Desinstaller SpeakToFR"; Filename: "{uninstallexe}"

[Tasks]
Name: "autorun"; Description: "Lancer SpeakToFR au demarrage de Windows"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SpeakToFR"; ValueData: """{app}\SpeakToFR.exe"""; Tasks: autorun

[Run]
Filename: "{app}\SpeakToFR.exe"; Description: "Demarrer SpeakToFR"; Flags: nowait postinstall skipifsilent
Filename: "{app}\help.html"; Description: "Ouvrir l'aide"; Flags: postinstall shellexec skipifsilent

[Code]
function KillProcess(const FileName: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('taskkill.exe', '/F /IM "' + FileName + '" /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  KillProcess('SpeakToFR.exe');
  Result := True;
end;
