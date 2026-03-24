@echo off
setlocal EnableDelayedExpansion

set "APPDIR=%~dp0"
set "LOGFILE=%APPDIR%install_log.txt"

echo %DATE% %TIME% setup_whisper START >> "%LOGFILE%"

set "PY="
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
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

"!PY!" -m pip install openai-whisper -q >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% whisper exit=%ERRORLEVEL% >> "%LOGFILE%"

wmic path win32_VideoController get name 2>nul | findstr /i "nvidia" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo %DATE% %TIME% NVIDIA found - torch CUDA 12.4 >> "%LOGFILE%"
    "!PY!" -m pip install torch --index-url https://download.pytorch.org/whl/cu124 --force-reinstall -q >> "%LOGFILE%" 2>&1
) else (
    echo %DATE% %TIME% No NVIDIA - torch CPU >> "%LOGFILE%"
    "!PY!" -m pip install torch -q >> "%LOGFILE%" 2>&1
)
echo %DATE% %TIME% torch exit=%ERRORLEVEL% >> "%LOGFILE%"
echo %DATE% %TIME% DONE >> "%LOGFILE%"
exit /b 0
