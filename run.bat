@echo off
title Inkhwa - Manhwa Downloader
cd /d "%~dp0"

echo ============================================
echo   Inkhwa - Manhwa Downloader
echo ============================================
echo.

REM --- Check Python ------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Please install Python 3.10+
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM --- Check dependencies ------------------------------------------------
python -c "import PyQt6, undetected_chromedriver, selenium, requests, bs4, PIL" >nul 2>&1
if errorlevel 1 (
    echo [!] Installing dependencies...
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [X] pip install failed
        pause
        exit /b 1
    )
)

REM --- Auto-update before launch (git pull / zip) -----------------------
echo [*] Checking for updates...
python -m app.selfupdate
if %errorlevel% equ 2 (
    echo [*] Updated to the latest version. Relaunching...
    start "" "%~f0"
    exit /b 0
)

REM --- Run app -----------------------------------------------------------
python manhwa_dl.py
if errorlevel 1 (
    echo.
    echo [X] App exited with error
    pause
)
