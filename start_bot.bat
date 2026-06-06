@echo off
chcp 65001 >nul
title Notification Bot

echo ============================================
echo   Telegram Bot - Notion
echo ============================================
echo.

cd /d "%~dp0"

if not exist ".venv\" (
    echo [1/3] Creating venv...
    python -m venv .venv
)

echo [2/3] Installing deps...
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist ".env" (
    copy .env.example .env
    echo.
    echo Edit .env with your tokens, then run again.
    pause
    exit /b 1
)

echo [3/3] Starting bot...
echo.
python main.py

pause
