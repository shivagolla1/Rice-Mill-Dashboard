@echo off
title Rice Mill Dashboard - Sync Now
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
echo  Rice Mill Dashboard - Manual Cloud Sync
echo ====================================================
echo.

"%PYTHON%" "%SCRIPT_DIR%local_sync_agent.py" --once

echo.
pause
