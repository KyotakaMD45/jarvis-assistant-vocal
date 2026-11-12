@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Jarvis is not installed.
    ping -n 4 127.0.0.1 >nul
    exit /b 1
)
".venv\Scripts\python.exe" -m jarvis --quit
ping -n 3 127.0.0.1 >nul
