@echo off
setlocal EnableDelayedExpansion

set "APPDIR=%~dp0"
set "PY=%APPDIR%python\python.exe"
set "LOGFILE=%APPDIR%install_log.txt"
set "PTH=%APPDIR%python\python313._pth"

echo %DATE% %TIME% START >> "%LOGFILE%"

REM Write correct .pth (enables tkinter and site-packages)
(
    echo python313.zip
    echo .
    echo Lib\site-packages
    echo import site
) > "%PTH%"
echo %DATE% %TIME% .pth ok >> "%LOGFILE%"

REM Install pip
"%PY%" "%APPDIR%python\get-pip.py" --no-warn-script-location -q >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% pip exit=%ERRORLEVEL% >> "%LOGFILE%"

REM Install base packages
echo %DATE% %TIME% base packages >> "%LOGFILE%"
"%PY%" -m pip install beautifulsoup4 customtkinter imageio-ffmpeg openai-whisper certifi tkinterdnd2 -q >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% base exit=%ERRORLEVEL% >> "%LOGFILE%"

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
