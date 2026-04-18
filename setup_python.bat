@echo off
setlocal EnableDelayedExpansion

set "APPDIR=%~dp0"
set "LOGFILE=%APPDIR%install_log.txt"

echo %DATE% %TIME% START >> "%LOGFILE%"

REM Search Python 313, 312, 311, 310 in standard user locations
set "PY="
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
if "!PY!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"

REM Search via where (skip WindowsApps stub)
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

REM Upgrade pip
"!PY!" -m pip install --upgrade pip -q >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% pip upgrade exit=%ERRORLEVEL% >> "%LOGFILE%"

REM Install base packages
"!PY!" -m pip install beautifulsoup4 customtkinter imageio-ffmpeg openai-whisper certifi tkinterdnd2 -q >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% base packages exit=%ERRORLEVEL% >> "%LOGFILE%"

REM NVIDIA detection — install CUDA torch if found
powershell -NoProfile -Command "(Get-WmiObject Win32_VideoController).Name" 2>nul | findstr /i "nvidia" >nul
if !ERRORLEVEL!==0 (
    "%PY%" -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
    if !ERRORLEVEL!==0 (
        echo %DATE% %TIME% torch CUDA already OK, skip >> "%LOGFILE%"
        goto :done_torch
    )
    echo %DATE% %TIME% NVIDIA found - installing torch CUDA 12.8 (~2.5 GB... >> "%LOGFILE%"
    "%PY%" -m pip install torch --index-url https://download.pytorch.org/whl/cu128 --force-reinstall >> "%LOGFILE%" 2>&1
    echo %DATE% %TIME% torch CUDA exit=%ERRORLEVEL% >> "%LOGFILE%"
    "%PY%" -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.__version__)" >> "%LOGFILE%" 2>&1
) else (
    echo %DATE% %TIME% No NVIDIA - CPU torch >> "%LOGFILE%"
    "%PY%" -m pip install torch >> "%LOGFILE%" 2>&1
    echo %DATE% %TIME% torch CPU exit=%ERRORLEVEL% >> "%LOGFILE%"
)
:done_torch

echo %DATE% %TIME% DONE >> "%LOGFILE%"
exit /b 0
