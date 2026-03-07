@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set "SCRIPT=%~1"
set "PYTHON="
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" set "PYTHON=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
if "!PYTHON!"=="" if exist "C:\Python313\python.exe" set "PYTHON=C:\Python313\python.exe"
if "!PYTHON!"=="" if exist "C:\Python312\python.exe" set "PYTHON=C:\Python312\python.exe"
if "!PYTHON!"=="" (
    for /d %%v in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%v\python.exe" if "!PYTHON!"=="" set "PYTHON=%%v\python.exe"
    )
)
if "!PYTHON!"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 if "!PYTHON!"=="" set "PYTHON=%%i"
    )
)
if "!PYTHON!"=="" (
    echo [ERROR] Python not found. Install from: https://www.python.org/downloads/
    echo During install check "Add Python to PATH"
    pause & exit /b 1
)
echo Found Python: !PYTHON!
"!PYTHON!" "%SCRIPT%"
