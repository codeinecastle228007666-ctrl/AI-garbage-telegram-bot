@echo off
chcp 65001 >nul
title Bot Control Panel

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo ========================================
echo   Bot Control Panel
echo   http://localhost:8654
echo ========================================
echo.

start "" http://localhost:8654
python control_panel.py

pause
