@echo off
setlocal
cd /d "%~dp0"

echo Starting Stockwise Inventory Assistant...

where py >nul 2>nul
if %errorlevel%==0 (
  set PY_CMD=py -3
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 was not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
  )
  set PY_CMD=python
)

rem Free port 8003 if a previous server instance was left open
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8003 ^| findstr LISTENING 2^>nul') do taskkill /f /pid %%a >nul 2>&1

start "Inventory Assistant Server" cmd /k %PY_CMD% server.py
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8003/"
endlocal
