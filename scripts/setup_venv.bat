@echo off
rem Setup: create venv and install dependencies (Tsinghua mirror for CN network)
cd /d %~dp0
py -3 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
echo Done. Edit config.yaml, then run start_bot.bat
pause
