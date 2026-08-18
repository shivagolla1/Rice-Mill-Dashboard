@echo off
title Rice Mill Dashboard - 2-Click Cloud Sync
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -STA -File "%SCRIPT_DIR%sync_uploader.ps1"



