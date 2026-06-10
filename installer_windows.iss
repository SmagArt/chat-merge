#define AppName "Merge Chat"
#define AppVersion "2.7"
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
OutputBaseFilename=MergeChat_Setup_v{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[InstallDelete]
; Убираем старые torch/whisper при переустановке — иначе CPU-torch от прошлой сборки
; переживает новый exe и Whisper работает через CPU даже на машинах с NVIDIA.
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\torch"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\torch-*"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\whisper"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\openai_whisper*"
Type: files; Name: "{app}\__pycache__\*"

[Files]
; Full Python installer — installs to {app}\python (requires admin + Python not already installed)
Source: "python-installer\python-3.13.2-amd64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall

Source: "merge_chat.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_1024.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup_base.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup_whisper.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher_win.vbs"; DestDir: "{app}"; Flags: ignoreversion
; Только сам скрипт выгрузки ВК — НЕ tools\*, иначе уедут .env (токен) и vk_export (личные данные)
Source: "tools\vk_fetch_history.py"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\merge_chat.ico"; Tasks: desktopicon

[Run]
; Step 1: Install Python 3.13 to {app}\python
Filename: "{tmp}\python-3.13.2-amd64.exe"; Parameters: "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 SimpleInstall=1 TargetDir=""{app}\python"""; StatusMsg: "Установка Python 3.13..."; Flags: waituntilterminated

; Step 2: Base packages (~50 MB)
Filename: "{app}\setup_base.bat"; WorkingDir: "{app}"; StatusMsg: "Установка базовых пакетов..."; Flags: waituntilterminated runhidden

; Step 3: Create pkgs_ok flag — launcher стартует сразу без проверок
Filename: "cmd.exe"; Parameters: "/c echo done > ""{app}\pkgs_ok.flag"""; Flags: runhidden waituntilterminated

; Step 4: Optional launch
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher_win.vbs"""; WorkingDir: "{app}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; Сносим всю папку установки целиком. Изоляция служебных файлов: whisper/torch
; (local_packages), скачанные модели (whisper_models), конфиг, логи, pkgs_ok.flag
; и __pycache__ создаются ВНУТРИ {app} — поэтому удаление {app} вычищает всё.
; Общий ~/.cache/whisper намеренно НЕ трогаем из тихого деинсталлятора (его
; может использовать другая прога — voice-diarizer); он чистится осознанно
; через кнопку «Удалить Whisper» в GUI.
Type: filesandordirs; Name: "{app}"
