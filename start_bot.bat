@echo off
rem Start the QQ chat bot (requires NapCat running first)
cd /d %~dp0
venv\Scripts\python.exe main.py
pause
