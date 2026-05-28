@echo off
title Inkhwa - Install
cd /d "%~dp0"

echo ============================================
echo   Inkhwa - Install dependencies
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Please install Python 3.10+
    echo     https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version
echo.
echo [*] Upgrading pip ...
python -m pip install --upgrade pip --disable-pip-version-check

echo.
echo [*] Installing dependencies from requirements.txt ...
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo [X] pip install failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Install complete - run.bat to start
echo ============================================
pause
