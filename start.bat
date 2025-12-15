@echo off
:restart
cd /d "D:\bot diskord"
python main.py
echo Bot crashed or stopped. Restarting in 5 seconds...
timeout /t 5
goto restart
