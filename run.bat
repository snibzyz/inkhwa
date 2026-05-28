@echo off
chcp 65001 >nul
title Inkhwa — Manhwa Downloader
cd /d "%~dp0"

echo ============================================
echo   Inkhwa — Manhwa Downloader
echo ============================================
echo.

REM --- ตรวจสอบ Python -----------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] ไม่พบ Python กรุณาติดตั้ง Python 3.10+
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM --- ตรวจสอบ dependencies ----------------------------------------------
python -c "import PyQt6, undetected_chromedriver, selenium, requests, bs4" >nul 2>&1
if errorlevel 1 (
    echo [!] ติดตั้ง dependencies...
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [X] pip install ล้มเหลว
        pause
        exit /b 1
    )
)

REM --- รันโปรแกรม ---------------------------------------------------------
python manhwa_dl.py
if errorlevel 1 (
    echo.
    echo [X] โปรแกรมจบด้วย error
    pause
)
