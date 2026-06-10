@echo off
rem ============================================================
rem  vk_fetch.bat - quick VK dialog export
rem  Double-click -> asks peer_id -> downloads via VK API.
rem  Token is read from tools\.env (VK_TOKEN, or VK_TOKEN_<NAME>).
rem  Usage:  vk_fetch.bat [peer_id] [account_name]
rem    account_name (optional) -> token VK_TOKEN_<NAME> from tools\.env
rem    (omit it to use the default VK_TOKEN)
rem ============================================================
setlocal
cd /d "%~dp0"
set "NO_PROXY=.vk.com,.vk.ru,.userapi.com"

set "PEER=%~1"
set "ACCT=%~2"
set "ACCTARG="
if not "%ACCT%"=="" set "ACCTARG=--account %ACCT%"

if "%PEER%"=="" set /p PEER="Enter peer_id (e.g. 12345678): "
if "%PEER%"=="" (
  echo No peer_id given. Bye.
  goto :end
)

echo.
echo Fetching dialog %PEER% ...
echo.
py tools\vk_fetch_history.py --peer %PEER% %ACCTARG%
if errorlevel 1 (
  echo.
  echo FAILED. Check token in tools\.env, or list dialogs:
  echo   py tools\vk_fetch_history.py --list
) else (
  echo.
  echo OK. Saved: tools\vk_export\%PEER%.json
  echo Drop that .json into a folder and run Merge Chat on it.
)

:end
echo.
pause
endlocal
