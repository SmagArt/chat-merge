@echo off
setlocal EnableDelayedExpansion

REM Base packages go INSIDE the app folder (base_packages), not into the
REM system Python's site-packages. Otherwise uninstalling MergeChat leaves
REM customtkinter/bs4/tkinterdnd2 behind in someone else's interpreter.
REM whisper and torch live separately, in local_packages: the "Remove
REM Whisper" button wipes that one, and the window must still open after.

set "APPDIR=%~dp0"
set "LOGFILE=%APPDIR%install_log.txt"
set "BASEPKGS=%APPDIR%base_packages"

echo %DATE% %TIME% setup_base START >> "%LOGFILE%"

set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
if "!PY!"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 if "!PY!"=="" set "PY=%%i"
    )
)

if "!PY!"=="" (
    echo %DATE% %TIME% ERROR: Python not found >> "%LOGFILE%"
    exit /b 1
)

echo %DATE% %TIME% Python: !PY! >> "%LOGFILE%"
REM Remember which interpreter was used - the uninstaller needs it to
REM purge packages that OLD versions put into the system Python.
> "%APPDIR%python_path.txt" echo !PY!
echo %DATE% %TIME% Target: !BASEPKGS! >> "%LOGFILE%"

REM Restore pip via ensurepip if missing (e.g. site-packages was cleaned)
"!PY!" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo %DATE% %TIME% pip missing, bootstrapping via ensurepip >> "%LOGFILE%"
    "!PY!" -m ensurepip --upgrade >> "%LOGFILE%" 2>&1
)

mkdir "!BASEPKGS!" 2>nul

REM --target puts packages in the app folder. --upgrade is needed so that
REM reinstalling over an older version refreshes them instead of skipping.
REM Upper bounds are deliberate: customtkinter 6.0 is tested and works, but
REM an unpinned major bump would break the UI silently on a future install.
"!PY!" -m pip install --no-user --target "!BASEPKGS!" --upgrade beautifulsoup4 "customtkinter>=5.2,<7" imageio-ffmpeg certifi "tkinterdnd2>=0.4,<1" requests >> "%LOGFILE%" 2>&1
set "RC=!ERRORLEVEL!"
echo %DATE% %TIME% base packages exit=!RC! >> "%LOGFILE%"

REM Verify the import comes FROM base_packages, not from the system Python:
REM an old system-wide customtkinter would otherwise mask a failed install.
"!PY!" -c "import sys; sys.path.insert(0, r'!BASEPKGS!'); import customtkinter, bs4, tkinterdnd2; print('base packages OK')" >> "%LOGFILE%" 2>&1
set "CHK=!ERRORLEVEL!"
echo %DATE% %TIME% base check exit=!CHK! >> "%LOGFILE%"

REM Precompile .pyc for faster cold start
"!PY!" -m compileall -q "%APPDIR%merge_chat.py" "%APPDIR%merge_chat_gui.py" >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% compileall exit=!ERRORLEVEL! >> "%LOGFILE%"

echo %DATE% %TIME% DONE >> "%LOGFILE%"
if not "!CHK!"=="0" exit /b 1
exit /b 0
