@echo off
title Rice Mill Dashboard - Cloud Sync Agent
setlocal

set "SCRIPT_DIR=%~dp0"
set "BUNDLED_PY=%SCRIPT_DIR%runtime\python38\python.exe"

if exist "%BUNDLED_PY%" (
    set "PYTHON=%BUNDLED_PY%"
) else (
    set "PYTHON=python"
)

echo.
echo ====================================================
echo  Rice Mill Dashboard - Starting Cloud Sync Agent
echo ====================================================
echo.

"%PYTHON%" "%SCRIPT_DIR%local_sync_agent.py"

pause
