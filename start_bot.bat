@echo off
chcp 65001 >nul
cd /d "D:\bot diskord"
echo [START] Запускаю бота с виртуального окружения...
"D:\bot diskord\.venv\Scripts\python.exe" "D:\bot diskord\main.py"
pause
