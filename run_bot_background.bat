@echo off
setlocal enabledelayedexpansion

:restart
cd /d "D:\bot diskord"
echo Запускаю бота...
python main.py

echo Бот упал, перезагружаю через 5 секунд...
timeout /t 5 /nobreak
goto restart
