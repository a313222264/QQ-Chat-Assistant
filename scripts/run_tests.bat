@echo off
rem Run all regression tests (no QQ account needed)
cd /d %~dp0
echo === mock_test ===
venv\Scripts\python.exe scripts\mock_test.py
echo.
echo === ws_integration_test ===
venv\Scripts\python.exe scripts\ws_integration_test.py
pause
