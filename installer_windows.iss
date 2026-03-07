#define AppName "Merge Chat"
#define AppVersion "2.0"
#define AppPublisher "Artem Smagin"
#define AppURL "https://github.com/SmagArt/chat-merge"

[Setup]
AppId={{B7F2C4A1-3D8E-4F92-A6B1-9C5D2E7F3A80}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
SetupIconFile=merge_chat.ico
UninstallDisplayIcon={app}\merge_chat.ico
OutputDir=dist_installer
OutputBaseFilename=MergeChat_Setup_v{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
; Full Python installer (download via prepare_installer.bat before building)
Source: "python-installer\python-3.13.2-amd64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
; App files
Source: "merge_chat.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_1024.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup_python.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher_win.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"; Tasks: desktopicon

[Run]
; Step 1: Install Python silently (full installer, includes tkinter)
Filename: "{tmp}\python-3.13.2-amd64.exe"; Parameters: "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 TargetDir={app}\python"; StatusMsg: "Установка Python..."; Flags: waituntilterminated

; Step 2: Install packages (GUI progress via setup_python.bat)
Filename: "{app}\setup_python.bat"; WorkingDir: "{app}"; StatusMsg: "Установка пакетов..."; Flags: waituntilterminated runhidden

; Step 3: Optional launch
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
