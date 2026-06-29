@echo off
:: ============================================================
::  Rice Mill Dashboard - Auto-Start on Windows Login
::
::  HOW TO USE:
::    Set AUTOSTART=ON  below → run this file → auto-start ENABLED
::    Set AUTOSTART=OFF below → run this file → auto-start DISABLED
::
::  NOTE: Run as Administrator for best results.
::        Right-click this file → "Run as administrator"
:: ============================================================

set AUTOSTART=OFF

:: ── Task name (do not change) ────────────────────────────────
set TASKNAME=Rice Mill Dashboard Auto-Start

echo.
echo  ============================================
echo   Rice Mill Dashboard - Auto-Start Setup
echo   Current setting: AUTOSTART=%AUTOSTART%
echo  ============================================
echo.

if /i "%AUTOSTART%"=="ON"  goto :enable
if /i "%AUTOSTART%"=="OFF" goto :disable

echo  ERROR: AUTOSTART must be ON or OFF. Edit this file and try again.
echo.
pause
exit /b 1

:: ── ENABLE ──────────────────────────────────────────────────
:enable
echo  Registering Task Scheduler entry...
echo  Task    : "%TASKNAME%"
echo  Trigger : On Windows login (any user)
echo  Action  : Run start.bat
echo.
schtasks /create /tn "%TASKNAME%" /tr "\"%~dp0..\start.bat\"" /sc onlogon /rl highest /f >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  SUCCESS: Rice Mill Dashboard will now start automatically every time
    echo           someone logs into Windows.
    echo.
    echo  To disable: open this file, set AUTOSTART=OFF, run again.
) else (
    echo  ERROR: Could not register the task.
    echo  Try right-clicking this file and choosing "Run as administrator".
)
echo.
pause
exit /b

:: ── DISABLE ─────────────────────────────────────────────────
:disable
echo  Removing Task Scheduler entry (if it exists)...
schtasks /delete /tn "%TASKNAME%" /f >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  SUCCESS: Auto-start has been disabled.
    echo           The dashboard will no longer start on login.
) else (
    echo  Note: Auto-start task was not registered. Nothing to remove.
)
echo.
echo  To enable later: open this file, set AUTOSTART=ON, run again.
echo.
pause
exit /b
