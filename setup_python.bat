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
REM cu124 required for Python 3.13 (cu121 only supports up to 3.12)
wmic path win32_VideoController get name 2>nul | findstr /i "nvidia" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo %DATE% %TIME% NVIDIA found - installing torch CUDA 12.4 >> "%LOGFILE%"
    "%PY%" -m pip install torch --index-url https://download.pytorch.org/whl/cu124 --force-reinstall -q >> "%LOGFILE%" 2>&1
    echo %DATE% %TIME% torch CUDA exit=%ERRORLEVEL% >> "%LOGFILE%"
    REM Verify CUDA actually works
    "%PY%" -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.__version__)" >> "%LOGFILE%" 2>&1
) else (
    echo %DATE% %TIME% No NVIDIA - CPU torch >> "%LOGFILE%"
    "%PY%" -m pip install torch -q >> "%LOGFILE%" 2>&1
    echo %DATE% %TIME% torch CPU exit=%ERRORLEVEL% >> "%LOGFILE%"
)

echo %DATE% %TIME% DONE >> "%LOGFILE%"
exit /b 0
