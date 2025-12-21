[Setup]
AppName=SpeakToFR
AppVersion=1.0.0
AppPublisher=SpeakToFR
DefaultDirName={pf}\SpeakToFR
DefaultGroupName=SpeakToFR
DisableProgramGroupPage=yes
OutputBaseFilename=SetupSpeakToFR
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\SpeakToFR.exe
PrivilegesRequired=admin

[Files]
Source: "dist\SpeakToFR.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "codex_tts\window_prefs.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SpeakToFR"; Filename: "{app}\SpeakToFR.exe"
Name: "{group}\Desinstaller SpeakToFR"; Filename: "{uninstallexe}"

[Tasks]
Name: "autorun"; Description: "Lancer SpeakToFR au demarrage de Windows"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SpeakToFR"; ValueData: """{app}\SpeakToFR.exe"""; Tasks: autorun

[Run]
Filename: "{app}\SpeakToFR.exe"; Description: "Demarrer SpeakToFR"; Flags: nowait postinstall skipifsilent
