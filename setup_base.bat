@echo off
setlocal EnableDelayedExpansion

set "APPDIR=%~dp0"
set "LOGFILE=%APPDIR%install_log.txt"

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

REM Restore pip via ensurepip if missing (e.g. site-packages was cleaned)
"!PY!" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo %DATE% %TIME% pip missing, bootstrapping via ensurepip >> "%LOGFILE%"
    "!PY!" -m ensurepip --upgrade >> "%LOGFILE%" 2>&1
)

REM Ensure site-packages dir exists so pip installs there, not user site
for %%D in ("!PY!") do set "PYDIR=%%~dpD"
mkdir "!PYDIR!Lib\site-packages" 2>nul

"!PY!" -m pip install --upgrade pip --no-user -q >> "%LOGFILE%" 2>&1
"!PY!" -m pip install --no-user beautifulsoup4 customtkinter imageio-ffmpeg certifi tkinterdnd2 >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% base packages exit=%ERRORLEVEL% >> "%LOGFILE%"

REM Verify customtkinter importable
"!PY!" -c "import customtkinter; print('customtkinter OK')" >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% ctk check exit=%ERRORLEVEL% >> "%LOGFILE%"
echo %DATE% %TIME% DONE >> "%LOGFILE%"
exit /b 0
