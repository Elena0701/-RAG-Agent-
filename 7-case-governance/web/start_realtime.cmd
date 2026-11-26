@echo off
setlocal
cd /d "%~dp0"
if not exist "..\..\4-agent\code\.venv\Scripts\python.exe" (
  echo Existing Agent virtual environment not found. See ..\WEB_DELIVERY.md.
  pause
  exit /b 1
)
"..\..\4-agent\code\.venv\Scripts\python.exe" -B -u app.py --port 8766
if errorlevel 1 pause
endlocal
