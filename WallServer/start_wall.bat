@echo off
rem Starts the Wall server and opens the wall display fullscreen on this machine.
cd /d "%~dp0"
start "Wall server" python server.py
timeout /t 3 /nobreak >nul

set "URL=http://localhost:8765"
set "BROWSER="
if exist "%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BROWSER=%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"
if not defined BROWSER if exist "%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BROWSER=%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

if defined BROWSER (
  start "" "%BROWSER%" --kiosk "%URL%" --autoplay-policy=no-user-gesture-required --user-data-dir="%~dp0browser-profile"
) else (
  start "" "%URL%"
)
