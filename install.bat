@echo off
chcp 65001 >nul
title Inkhwa — Install
cd /d "%~dp0"

echo ============================================
echo   Inkhwa — Install dependencies
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [X] ไม่พบ Python กรุณาติดตั้ง Python 3.10+
    echo     https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version
echo.
echo [*] อัปเดต pip ...
python -m pip install --upgrade pip --disable-pip-version-check

echo.
echo [*] ติดตั้ง dependencies จาก requirements.txt ...
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo [X] pip install ล้มเหลว
    pause
    exit /b 1
)

echo.
echo ============================================
echo   ติดตั้งเสร็จ — run.bat เพื่อเริ่มใช้งาน
echo ============================================
pause
