@echo off
setlocal enabledelayedexpansion

title OLT ONT Unlock Tool - Setup

echo.
echo =====================================================
echo   OLT ONT / ONU Unlock Tool - Windows Setup
echo =====================================================
echo.

:: ── Check Python ──────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please download and install Python from:
    echo   https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found.

:: ── Create virtual environment ─────────────────────────
if exist env\Scripts\activate.bat (
    echo [OK] Virtual environment already exists.
) else (
    echo [..] Creating virtual environment...
    python -m venv env
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: ── Activate venv ─────────────────────────────────────
call env\Scripts\activate.bat

:: ── Install dependencies ───────────────────────────────
echo [..] Installing dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: ── Django setup ──────────────────────────────────────
echo [..] Running Django migrations...
python manage.py migrate --run-syncdb >nul 2>&1
echo [OK] Database ready.

if not exist ".sessions" mkdir .sessions

:: ── Done ──────────────────────────────────────────────
echo.
echo =====================================================
echo   Setup complete!
echo =====================================================
echo.
echo To start the server, run:
echo   start.bat
echo.
echo Or run now? (press any key to start, close window to skip)
pause

call start.bat
