@echo off
setlocal EnableDelayedExpansion
REM prepare_installer.bat
REM Downloads full Python installer for Inno Setup bundling
REM Run ONCE before building MergeChat_Setup.exe

if not exist "python-installer" mkdir "python-installer"

echo Downloading Python 3.13.2 full installer (~26 MB)...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe' -OutFile 'python-installer\python-3.13.2-amd64.exe'"

if exist "python-installer\python-3.13.2-amd64.exe" (
    echo Done! Now open installer_windows.iss in Inno Setup and press Build.
) else (
    echo ERROR: download failed. Check internet connection.
)
pause
