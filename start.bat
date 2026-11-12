@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Jarvis is not installed yet. Running install.bat first...
    call install.bat --no-pause
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

rem Options that need this console window (setup, tests, keyboard mode, control).
set "CONSOLE="
for %%A in (%*) do (
    for %%B in (--text --test --setup-key --setup-key-if-missing --voice-test --setup-model --console --quit --show --restart --help -h) do (
        if /i "%%~A"=="%%B" set "CONSOLE=1"
    )
)
if defined CONSOLE goto :console

rem Default: background mode (no console). Jarvis lives in the tray icon near the clock.
rem Redirections: the background process must not keep this window's handles open.
start "" ".venv\Scripts\pythonw.exe" -m jarvis %* <nul >nul 2>nul
echo Jarvis is starting in the background (icon near the clock).
echo You can close this window. Right-click the icon to quit or restart.
ping -n 4 127.0.0.1 >nul
exit /b 0

:console
chcp 65001 >nul
".venv\Scripts\python.exe" -m jarvis %*
if errorlevel 1 pause
exit /b
