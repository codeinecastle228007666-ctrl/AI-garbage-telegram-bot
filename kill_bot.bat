@echo off
chcp 65001 >nul
title Kill Bot

echo Killing any existing bot instances...

wmic process where "commandline like '%%main.py%%' and name like '%%python%%'" delete >nul 2>&1

echo Looking for stale python processes...
for /f "tokens=2 delims=," %%a in ('wmic process where "commandline like '%%main.py%%'" get processid /format:csv 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

wmic process where "commandline like '%%main.py%%'" get processid,commandline /format:csv 2>nul | findstr /i "main.py" >nul && (
    echo [WARN] Could not kill bot. Try manually: taskkill /f /im python.exe
) || (
    echo Bot process killed.
)

pause
