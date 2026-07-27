@echo off
title Rebuilding Rice Mill Dashboard...
cd /d "%~dp0App"

if exist C:\Python38-32\python.exe (
    echo [INFO] Found 32-bit Python 3.8 environment. Starting compilation...
    C:\Python38-32\python.exe package.py
) else (
    echo [WARNING] 32-bit Python 3.8 not found at C:\Python38-32\python.exe.
    echo Rebuilding with default system Python...
    python package.py
)

pause
