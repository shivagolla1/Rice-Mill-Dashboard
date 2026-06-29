@echo off
title Rice Mill Dashboard
setlocal

:: Get folder path of start.bat
set "SCRIPT_DIR=%~dp0"
set "BUNDLED_PY=%SCRIPT_DIR%runtime\python38\python.exe"

if exist "%BUNDLED_PY%" (
    set "PYTHON=%BUNDLED_PY%"
) else (
    set "PYTHON=python"
)

echo.
echo  ============================================
echo   Rice Mill Dashboard - Starting Server
echo  ============================================
echo.

:: Kill any existing server on port 5000 (Win7 compatible)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Open the browser after 3 seconds in the background
start /min cmd /c "ping 127.0.0.1 -n 3 >nul && start http://localhost:5000"

echo  ============================================
echo   Dashboard is running!
echo.
echo   To close, click "Close Dashboard" in the browser
echo   or close this command window.
echo  ============================================
echo.

:: Go to App folder and run Python directly in this window
cd /d "%SCRIPT_DIR%App"
"%PYTHON%" app.py

exit
