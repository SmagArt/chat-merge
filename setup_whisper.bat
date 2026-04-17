@echo off
setlocal EnableDelayedExpansion

set "APPDIR=%~dp0"
set "LOGFILE=%APPDIR%install_log.txt"

echo %DATE% %TIME% setup_whisper START >> "%LOGFILE%"
echo [PHASE:CHECKING] >> "%LOGFILE%"

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

for %%D in ("!PY!") do set "PYDIR=%%~dpD"
mkdir "!PYDIR!Lib\site-packages" 2>nul

echo [PHASE:DOWNLOAD_WHISPER] >> "%LOGFILE%"
"!PY!" -m pip install --no-user openai-whisper >> "%LOGFILE%" 2>&1
echo %DATE% %TIME% whisper exit=!ERRORLEVEL! >> "%LOGFILE%"

powershell -NoProfile -Command "(Get-WmiObject Win32_VideoController).Name" 2>nul | findstr /i "nvidia" >nul
if !ERRORLEVEL!==0 (
    "!PY!" -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
    if !ERRORLEVEL!==0 (
        echo %DATE% %TIME% torch CUDA already OK, skip >> "%LOGFILE%"
        goto :done_torch
    )
    echo [PHASE:DOWNLOAD_TORCH_CUDA] >> "%LOGFILE%"
    echo %DATE% %TIME% NVIDIA found - installing torch CUDA 12.8 >> "%LOGFILE%"
    "!PY!" -m pip install torch --index-url https://download.pytorch.org/whl/cu128 --force-reinstall >> "%LOGFILE%" 2>&1
) else (
    echo [PHASE:DOWNLOAD_TORCH_CPU] >> "%LOGFILE%"
    echo %DATE% %TIME% No NVIDIA - torch CPU >> "%LOGFILE%"
    "!PY!" -m pip install torch >> "%LOGFILE%" 2>&1
)
:done_torch
echo %DATE% %TIME% torch exit=!ERRORLEVEL! >> "%LOGFILE%"
echo [PHASE:DONE] >> "%LOGFILE%"
echo %DATE% %TIME% DONE >> "%LOGFILE%"
exit /b 0
