@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

REM Merge Chat v2.1 - install for existing Python users

set "PYTHON="

REM Search Python 313, 312, 311, 310
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"

REM Search via where (skip WindowsApps stub)
if "!PYTHON!"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 if "!PYTHON!"=="" set "PYTHON=%%i"
    )
)

if "!PYTHON!"=="" (
    echo Python not found. Install Python 3.10-3.13 from python.org
    pause
    exit /b 1
)

echo Python: !PYTHON!
echo.

REM Upgrade pip
"!PYTHON!" -m pip install --upgrade pip -q

REM Install packages
echo Installing packages...
"!PYTHON!" -m pip install beautifulsoup4 customtkinter imageio-ffmpeg openai-whisper certifi tkinterdnd2
if errorlevel 1 (
    echo.
    echo ERROR: package install failed. See above.
    pause
    exit /b 1
)

REM Check if torch CUDA already available
"!PYTHON!" -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>nul
if %errorlevel%==0 (
    echo PyTorch CUDA already available - skipping torch install.
) else (
    wmic path win32_VideoController get name 2>nul | findstr /i nvidia >nul
    if !errorlevel!==0 (
        echo NVIDIA GPU detected - installing PyTorch CUDA...
        "!PYTHON!" -m pip install torch --index-url https://download.pytorch.org/whl/cu124
    ) else (
        echo Installing PyTorch CPU...
        "!PYTHON!" -m pip install torch
    )
)

REM Create shortcut
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut(\"$desktop\Merge Chat.lnk\"); $s.TargetPath='%SystemRoot%\System32\wscript.exe'; $s.Arguments='\"%SCRIPT_DIR%launcher_win.vbs\"'; $s.WorkingDirectory='%SCRIPT_DIR%'; $s.IconLocation='%SCRIPT_DIR%merge_chat.ico'; $s.Save()"

echo.
echo Done! Shortcut created on Desktop.
pause
