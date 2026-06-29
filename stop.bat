@echo off
title Rice Mill Dashboard - Stop Server
echo.
echo  ============================================
echo   Rice Mill Dashboard - Stopping Server
echo  ============================================
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr :5000 ^| findstr LISTENING') do (
    echo  Stopping server process ^(PID %%a^)...
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

if "%FOUND%"=="0" (
    echo  No server found running.
    echo  ^(It may have already been stopped or auto-stopped due to inactivity.^)
) else (
    echo  Server stopped successfully.
)

echo.
ping 127.0.0.1 -n 3 >nul
