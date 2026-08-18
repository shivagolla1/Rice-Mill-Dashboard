@echo off
title Rice Mill Dashboard - Desktop Shortcut Creator
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "CONFIG_FILE=%SCRIPT_DIR%sync_config.txt"

set "CLOUD_URL=https://ricemilldashboard.up.railway.app"
set "COMPANY_CODE=DEMO"
set "SYNC_SECRET_TOKEN=RiceMillSyncSecretToken2026!"

if exist "%CONFIG_FILE%" (
    for /f "usebackq tokens=1,2 delims==" %%a in ("%CONFIG_FILE%") do (
        set "k=%%a"
        set "v=%%b"
        if "!k!"=="CLOUD_URL" set "CLOUD_URL=!v!"
        if "!k!"=="COMPANY_CODE" set "COMPANY_CODE=!v!"
        if "!k!"=="SYNC_SECRET_TOKEN" set "SYNC_SECRET_TOKEN=!v!"
        if "!k!"=="LICENSE_KEY" if "!SYNC_SECRET_TOKEN!"=="" set "SYNC_SECRET_TOKEN=!v!"
    )
)

set "TARGET_URL=%CLOUD_URL%/quick-upload?code=%COMPANY_CODE%&token=%SYNC_SECRET_TOKEN%"

powershell -ExecutionPolicy Bypass -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $desktop 'Upload Database to Cloud.url'; $writer=[System.IO.File]::CreateText($lnk); $writer.WriteLine('[InternetShortcut]'); $writer.WriteLine('URL=%TARGET_URL%'); $writer.WriteLine('IconIndex=0'); $writer.Close()"

echo.
echo ====================================================
echo  [SUCCESS] Desktop Shortcut Created!
echo ====================================================
echo.
echo  Shortcut Name: Upload Database to Cloud.url
echo  Target URL:   %TARGET_URL%
echo.
echo  Double-click "Upload Database to Cloud" on your
echo  Desktop anytime to sync your database.
echo.
pause
