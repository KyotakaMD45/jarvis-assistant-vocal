@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Jarvis - Install

echo ============================================
echo   JARVIS - installation
echo ============================================
echo.

echo [1/5] Looking for Python 3.10+ ...
call :find_python
if defined PY goto :have_python

echo       Python not found. Installing Python 3.12 with winget (no admin needed)...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if not defined PY goto :no_python

:have_python
%PY% --version

echo [2/5] Creating the virtual environment (.venv) ...
if exist ".venv\Scripts\python.exe" (
    echo       Already exists, reusing it.
) else (
    %PY% -m venv .venv
    if errorlevel 1 goto :venv_failed
)

echo [3/5] Installing dependencies (needs internet) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :pip_failed
echo       Done.

echo [4/5] French speech model (offline, about 41 MB) ...
".venv\Scripts\python.exe" -m jarvis --setup-model
if errorlevel 1 echo       [WARNING] Voice input will not work until the model is downloaded. Run install.bat again later.

echo [5/5] Claude API key ...
".venv\Scripts\python.exe" -m jarvis --setup-key-if-missing

echo.
echo ============================================
echo   Installation complete.
echo   - test.bat  : check internet, API key, microphone, speaker
echo   - start.bat : launch Jarvis (runs in the tray, near the clock)
echo   - stop.bat  : stop Jarvis
echo   Optional AIs: start.bat --setup-key groq / gemini / openai
echo ============================================
goto :end_ok


:find_python
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :eof
)
for %%V in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :eof
    )
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=python"
goto :eof


:no_winget
echo.
echo [ERROR] Python is not installed and winget is not available.
echo         Install Python 3.12 from https://www.python.org/downloads/
echo         (tick "Add python.exe to PATH"), then run install.bat again.
goto :end_fail

:no_python
echo.
echo [ERROR] Python could not be installed automatically.
echo         Install Python 3.12 from https://www.python.org/downloads/
echo         then run install.bat again.
goto :end_fail

:venv_failed
echo.
echo [ERROR] Could not create the virtual environment in "%CD%\.venv".
echo         Check that the folder is writable, then run install.bat again.
goto :end_fail

:pip_failed
echo.
echo [ERROR] Could not install the dependencies.
echo         Check your internet connection, then run install.bat again.
goto :end_fail


:end_ok
if /i not "%~1"=="--no-pause" pause
exit /b 0

:end_fail
if /i not "%~1"=="--no-pause" pause
exit /b 1
