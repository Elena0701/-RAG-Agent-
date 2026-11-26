@echo off
setlocal
cd /d "%~dp0"
"..\..\4-agent\code\.venv\Scripts\python.exe" -B -u app.py --port 8766 --lan
if errorlevel 1 pause
endlocal
