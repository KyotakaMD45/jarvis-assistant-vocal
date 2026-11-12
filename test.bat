@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Jarvis - Self-test

if not exist ".venv\Scripts\python.exe" (
    echo Jarvis is not installed yet. Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m jarvis --test
pause
