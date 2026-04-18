#define AppName "Merge Chat"
#define AppVersion "2.4"
#define AppPublisher "Artem Smagin"
#define AppURL "https://github.com/SmagArt/chat-merge"

[Setup]
AppId={{B7F2C4A1-3D8E-4F92-A6B1-9C5D2E7F3A80}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={localappdata}\Programs\MergeChat
DefaultGroupName={#AppName}
AllowNoIcons=yes
SetupIconFile=merge_chat.ico
UninstallDisplayIcon={app}\merge_chat.ico
OutputDir=dist_installer
OutputBaseFilename=MergeChat_Setup_v{#AppVersion}_noadmin
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "whisper"; Description: "Установить поддержку расшифровки голосовых сейчас (Whisper + PyTorch, 300 МБ – 2.5 ГБ)"; GroupDescription: "Компоненты:"; Flags: unchecked

[Files]
; No Python installer — uses system Python (must be pre-installed)
Source: "merge_chat.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_1024.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup_base.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup_whisper.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher_win.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"; Tasks: desktopicon

[Run]
; Step 1: Base packages into system Python (~50 MB)
Filename: "{app}\setup_base.bat"; WorkingDir: "{app}"; StatusMsg: "Установка базовых пакетов..."; Flags: waituntilterminated runhidden

; Step 2: Create pkgs_ok flag — launcher стартует сразу без проверок
Filename: "cmd.exe"; Parameters: "/c echo done > ""{app}\pkgs_ok.flag"""; Flags: runhidden waituntilterminated

; Step 3: Whisper + PyTorch (optional, if checkbox selected)
Filename: "{app}\setup_whisper.bat"; WorkingDir: "{app}"; StatusMsg: "Установка Whisper и PyTorch..."; Flags: waituntilterminated runhidden; Tasks: whisper

; Step 4: Optional launch
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
