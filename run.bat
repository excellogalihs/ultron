@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================================
echo   ULTRON - Local-First AI Assistant for Everyday Hardware
echo ========================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python was not found in your PATH.
    echo Please install Python 3.10+ from https://python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [ultron] Creating local virtual environment (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [ultron] Installing required dependencies...
    call .venv\Scripts\activate.bat
    python -m pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [NOTE] Ollama CLI was not detected in PATH.
    echo Ensure Ollama is installed and running at http://localhost:11434
) else (
    echo [ultron] Ollama CLI detected.
)

echo.
echo [ultron] Starting application at http://localhost:5000 ...
echo [ultron] Press Ctrl+C in this window to stop the server.
echo.

python app.py

pause
