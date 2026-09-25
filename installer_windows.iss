#define AppName "Merge Chat"
#define AppVersion "2.9.2"
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
; base_packages пересобираем начисто: они весят десятки мегабайт, а хвост от
; прошлой версии тут дороже, чем повторная установка. local_packages (whisper
; + torch, гигабайты) НЕ трогаем — переустановка не должна стоить 2.6 ГБ.
Type: filesandordirs; Name: "{app}\base_packages"
; Недокачанные колёса движка — мусор от прерванной установки, до 2.6 ГБ.
Type: filesandordirs; Name: "{app}\local_packages\_wheels"
Type: files; Name: "{app}\pkgs_ok.flag"
Type: files; Name: "{app}\__pycache__\*"

[Files]
; Full Python installer — installs to {app}\python (requires admin + Python not already installed)
Source: "python-installer\python-3.13.2-amd64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall

Source: "merge_chat.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "merge_chat_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "app_paths.py"; DestDir: "{app}"; Flags: ignoreversion
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

[Code]
// Пакеты проги с версии 2.9 лежат внутри {app} и уходят вместе с ней.
// Но версии до 2.9 ставили базовые пакеты (а когда-то и whisper с torch) в
// site-packages системного Python, и удаление папки их там не трогало.
// Предлагаем дочистить — но только по явному согласию и списком: эти же
// пакеты мог поставить себе кто-то другой.
const
  // customtkinter и beautifulsoup4 сюда НЕ входят намеренно: это ходовые
  // библиотеки, на которых легко сидит чужой скрипт того же пользователя
  // (проверено — сидит). Убираем только тяжёлое и профильное, что кроме
  // Merge Chat в системный Python ставить было некому.
  LEGACY_PKGS = 'openai-whisper torch tkinterdnd2 imageio-ffmpeg';

function GetRecordedPython(): String;
var
  S: AnsiString;
  P: Integer;
begin
  Result := '';
  // Путь к интерпретатору записал setup_base.bat при установке — это точнее,
  // чем гадать по стандартным местам, особенно под elevated-деинсталлятором.
  if LoadStringFromFile(ExpandConstant('{app}\python_path.txt'), S) then
  begin
    Result := Trim(String(S));
    P := Pos(#13, Result);
    if P > 0 then Result := Copy(Result, 1, P - 1);
    P := Pos(#10, Result);
    if P > 0 then Result := Copy(Result, 1, P - 1);
    Result := Trim(Result);
  end;
  if (Result <> '') and (not FileExists(Result)) then Result := '';
  // Бандленый Python лежит внутри {app} и уходит вместе с папкой — спрашивать
  // про «системный Python» тут бессмысленно. Раньше вопрос с путём
  // {app}\python\python.exe всплывал при каждом обычном удалении.
  if (Result <> '') and
     (Pos(Lowercase(AddBackslash(ExpandConstant('{app}'))), Lowercase(Result)) = 1) then
    Result := '';
end;

// ── Бандленый Python ───────────────────────────────────────────────────────
// Штатный установщик python.org ставит его per-user и регистрирует в
// «Установленных приложениях» + HKCU\Software\Python\PythonCore\3.13. Удаление
// папки {app} регистрацию не убирает: Python оставался в списке программ и в
// реестре, указывая в пустоту. Сносим его штатно — но ТОЛЬКО если он наш:
//   1) {app}\python\python.exe существует (TargetDir не был проигнорирован —
//      иначе Python уже стоял у пользователя до нас);
//   2) per-user регистрация 3.13 указывает внутрь {app}\python;
//   3) ровно один ключ удаления «Python 3.13.2 (64-bit)» с QuietUninstallString.
// Любое сомнение → не трогаем: снести пользователю его собственный Python
// (на нём сидят другие его программы) хуже, чем оставить запись в реестре.
function BundledPythonUninstallCmd(AppDir: String): String;
var
  Keys: TArrayOfString;
  I, Found: Integer;
  Key, Disp, Q, InstallPath: String;
begin
  Result := '';
  if not FileExists(AddBackslash(AppDir) + 'python\python.exe') then Exit;
  if not RegQueryStringValue(HKCU, 'Software\Python\PythonCore\3.13\InstallPath', '', InstallPath) then Exit;
  if Pos(Lowercase(AddBackslash(AddBackslash(AppDir) + 'python')),
         Lowercase(AddBackslash(InstallPath))) <> 1 then Exit;
  Found := 0;
  if RegGetSubkeyNames(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall', Keys) then
    for I := 0 to GetArrayLength(Keys) - 1 do
    begin
      Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + Keys[I];
      if RegQueryStringValue(HKCU, Key, 'DisplayName', Disp) and
         (CompareText(Trim(Disp), 'Python 3.13.2 (64-bit)') = 0) and
         RegQueryStringValue(HKCU, Key, 'QuietUninstallString', Q) and (Trim(Q) <> '') then
      begin
        Found := Found + 1;
        Result := Trim(Q);
      end;
    end;
  if Found <> 1 then Result := '';
end;

// "C:\path\x.exe" /uninstall /quiet  →  Exe + Params
procedure SplitCommand(Cmd: String; var Exe, Params: String);
var
  P: Integer;
begin
  Cmd := Trim(Cmd);
  if (Length(Cmd) > 0) and (Cmd[1] = '"') then
  begin
    Delete(Cmd, 1, 1);
    P := Pos('"', Cmd);
    if P = 0 then begin Exe := Cmd; Params := ''; Exit; end;
    Exe := Copy(Cmd, 1, P - 1);
    Params := Trim(Copy(Cmd, P + 1, Length(Cmd)));
  end else begin
    P := Pos(' ', Cmd);
    if P = 0 then begin Exe := Cmd; Params := ''; Exit; end;
    Exe := Copy(Cmd, 1, P - 1);
    Params := Trim(Copy(Cmd, P + 1, Length(Cmd)));
  end;
end;

procedure UninstallBundledPython();
var
  Cmd, Exe, Params: String;
  Code: Integer;
begin
  Cmd := BundledPythonUninstallCmd(ExpandConstant('{app}'));
  if Cmd = '' then Exit;
  SplitCommand(Cmd, Exe, Params);
  if FileExists(Exe) then
    Exec(Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

// ── Установка из-под ЧУЖОЙ учётной записи администратора ─────────────────
// Папка установки — в {localappdata} того, кто запустил повышенный установщик.
// Если UAC спросил пароль другого администратора, программа встала бы в ЕГО
// профиль, а у вошедшего пользователя не было бы ни ярлыка, ни доступа.
// Сравниваем профиль исходного пользователя (ExecAsOriginalUser) с текущим.
// Не удалось проверить — не мешаем (fail-open): ложный отказ хуже.
function OriginalUserProfile(): String;
var
  Marker: String;
  S: AnsiString;
  Code: Integer;
begin
  Result := '';
  Marker := ExpandConstant('{commonappdata}\MergeChat_setup_user.txt');
  DeleteFile(Marker);
  // "> file echo X" — не "echo X> file": профиль вида User2 дал бы "2>".
  if ExecAsOriginalUser(ExpandConstant('{cmd}'), '/c > "' + Marker + '" echo %USERPROFILE%',
                        '', SW_HIDE, ewWaitUntilTerminated, Code) then
    if LoadStringFromFile(Marker, S) then
      Result := Trim(String(S));
  DeleteFile(Marker);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Orig, Cur: String;
begin
  Result := '';
  Orig := OriginalUserProfile();
  Cur := GetEnv('USERPROFILE');
  if (Orig <> '') and (Cur <> '') and (CompareText(Orig, Cur) <> 0) then
    Result := 'Установщик получил права администратора от другой учётной записи.' + #13#10 +
              'Merge Chat ставится в личную папку пользователя, поэтому встал бы в профиль' + #13#10 +
              Cur + ',' + #13#10 + 'а не в ваш (' + Orig + ') — и у вас не запустился бы.' + #13#10#13#10 +
              'Чтобы поставить Merge Chat себе, вашей учётной записи нужны права' + #13#10 +
              'администратора — попросите администратора их выдать и запустите установку снова.';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Py: String;
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then Exit;
  // До удаления файлов: штатный деинсталлятор Python сам вычистит {app}\python
  // и свою регистрацию. Папку {app} после этого добьёт [UninstallDelete].
  UninstallBundledPython();
  Py := GetRecordedPython();
  if Py = '' then Exit;
  if MsgBox('Удалить также пакеты, которые прошлые версии Merge Chat'#13#10 +
            'поставили в системный Python?'#13#10#13#10 +
            Py + #13#10#13#10 +
            'Будут удалены: openai-whisper, torch, tkinterdnd2,'#13#10 +
            'imageio-ffmpeg. Это гигабайты.'#13#10#13#10 +
            'customtkinter и beautifulsoup4 НЕ трогаем — на них может'#13#10 +
            'держаться другой ваш скрипт.'#13#10#13#10 +
            'Нажмите «Нет», если этими пакетами пользуется что-то ещё.'#13#10 +
            'Сама Merge Chat их больше не использует: всё её хозяйство'#13#10 +
            'лежит внутри папки установки и удаляется в любом случае.',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    Exec(Py, '-m pip uninstall -y ' + LEGACY_PKGS, '', SW_HIDE,
         ewWaitUntilTerminated, Code);
    // Код возврата не проверяем: «пакета и не было» — не ошибка.
  end;
end;
