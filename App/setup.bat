@echo off
title SGRI Dashboard - Setup
color 0A
echo.
echo  ============================================
echo   SGRI Rice Mill Dashboard - Setup
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found!
    echo.
    echo  Download from: https://www.python.org/downloads/
    echo  IMPORTANT: Tick "Add Python to PATH" during install.
    echo.
    pause & exit /b 1
)

echo  Installing packages...
echo.
pip install flask openpyxl access_parser
echo.
echo  ============================================
echo   Setup complete!
echo  ============================================
echo.
echo  Next steps:
echo   1. Make sure data\SGRI_2025-2026.mdb is present
echo   2. Double-click start.bat to launch
echo.
pause
