@echo off
setlocal enabledelayedexpansion
title Rice Mill Dashboard - Installer
color 0A

echo.
echo  ====================================================
echo   Rice Mill Dashboard - Installation
echo  ====================================================
echo.
echo  This will set up the Rice Mill Dashboard on this PC.
echo  An internet connection is needed to download packages.
echo.

:: ── Paths ───────────────────────────────────────────────────────────────────
set "BASE=%~dp0"
set "RUNTIME=%BASE%runtime\python38"
set "PYTHON=%RUNTIME%\python.exe"
set "PTH_FILE=%RUNTIME%\python38._pth"
set "PIP=%RUNTIME%\Scripts\pip.exe"
set "APP_DIR=%BASE%App"
set "START_BAT=%BASE%start.bat"
:: Resolve actual Desktop path (handles OneDrive and other folder redirections)
set "DESKTOP=%USERPROFILE%\Desktop"
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v Desktop 2^>nul') do call set "DESKTOP=%%b"
set "SHORTCUT=%DESKTOP%\Rice Mill Dashboard.lnk"

:: ── Step 1: Check/Download bundled Python ───────────────────────────────────
echo  [1/4] Checking Python runtime...
if exist "%PYTHON%" (
    echo        Found existing Python runtime.
    goto :pip_setup
)

echo        Bundled Python not found. Downloading portable Python 3.8 (32-bit)...
if not exist "%BASE%runtime" mkdir "%BASE%runtime"

set "PY_URL=https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-win32.zip"
set "ZIP_PATH=%TEMP%\python-3.8.10-embed-win32.zip"

if exist "%ZIP_PATH%" del "%ZIP_PATH%"

powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%ZIP_PATH%'" >nul 2>&1

if not exist "%ZIP_PATH%" (
    echo.
    echo  ERROR: Could not download Python 3.8. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo        Extracting Python...
if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%"
mkdir "%RUNTIME%"
powershell -Command "Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%RUNTIME%'" >nul 2>&1
del "%ZIP_PATH%"

if not exist "%PYTHON%" (
    echo.
    echo  ERROR: Extraction failed or python.exe not found.
    echo.
    pause
    exit /b 1
)

:: Enable pip support in python38._pth by uncommenting 'import site'
if exist "%PTH_FILE%" (
    echo        Configuring Python environment...
    powershell -Command "(Get-Content '%PTH_FILE%') -replace '#import site', 'import site' | Set-Content '%PTH_FILE%'" >nul 2>&1
)

echo        Python runtime configured successfully.

:pip_setup
:: ── Step 2: Bootstrap pip ───────────────────────────────────────────────────
echo  [2/4] Setting up pip package manager...
if exist "%PIP%" (
    echo        pip already installed. Skipping.
    goto :install_packages
)

echo        Downloading pip bootstrap script...
if exist "%TEMP%\get-pip.py" del "%TEMP%\get-pip.py"
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/pip/3.8/get-pip.py' -OutFile '%TEMP%\get-pip.py'" >nul 2>&1

if not exist "%TEMP%\get-pip.py" (
    echo.
    echo  ERROR: Could not download pip. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo        Installing pip...
"%PYTHON%" "%TEMP%\get-pip.py" --quiet --no-warn-script-location
del "%TEMP%\get-pip.py"
echo        pip installed successfully.

:install_packages
:: ── Step 3: Install required packages ───────────────────────────────────────
if exist "%PYTHON%" (
    "%PYTHON%" -c "import flask, openpyxl, access_parser, PIL" >nul 2>&1
    if not errorlevel 1 (
        echo        All required packages are already installed. Skipping package setup.
        goto :create_shortcut
    )
)

echo  [3/4] Installing required packages (internet needed)...
echo        This may take 1-2 minutes...
echo.

"%PYTHON%" -m pip install --quiet --no-warn-script-location --upgrade pip
"%PYTHON%" -m pip install --quiet --no-warn-script-location flask
"%PYTHON%" -m pip install --quiet --no-warn-script-location openpyxl
"%PYTHON%" -m pip install --quiet --no-warn-script-location access_parser
"%PYTHON%" -m pip install --quiet --no-warn-script-location Pillow

if errorlevel 1 (
    echo.
    echo  WARNING: Some packages may not have installed correctly.
    echo  Try running install.bat again if the dashboard fails to start.
    echo.
) else (
    echo        All packages installed successfully.
)

:: Generate logo.ico from any logo image file (jpg, jpeg, png, bmp, webp) if it doesn't exist
if not exist "%APP_DIR%\static\logo.ico" (
    if exist "%PYTHON%" (
        "%PYTHON%" -c "from PIL import Image; import os; sd=os.path.join(r'%APP_DIR%','static'); l=[f for f in os.listdir(sd) if f.lower().startswith('logo') and f.lower().endswith(('.jpg','.jpeg','.png','.bmp','.webp'))]; Image.open(os.path.join(sd,l[0])).save(os.path.join(sd,'logo.ico'), format='ICO') if l else None" >nul 2>&1
    )
)

:create_shortcut
:: ── Step 4: Create Desktop shortcut ─────────────────────────────────────────
echo  [4/4] Creating Desktop shortcut...

echo Set ws = CreateObject("WScript.Shell") > "%TEMP%\shortcut.vbs"
echo Set s = ws.CreateShortcut("%SHORTCUT%") >> "%TEMP%\shortcut.vbs"
echo s.TargetPath = "cmd.exe" >> "%TEMP%\shortcut.vbs"
echo s.Arguments = "/c ""%START_BAT%""" >> "%TEMP%\shortcut.vbs"
echo s.WorkingDirectory = "%BASE%" >> "%TEMP%\shortcut.vbs"
echo s.WindowStyle = 7 >> "%TEMP%\shortcut.vbs"
echo s.IconLocation = "%APP_DIR%\static\logo.ico, 0" >> "%TEMP%\shortcut.vbs"
echo s.Description = "Rice Mill Dashboard" >> "%TEMP%\shortcut.vbs"
echo s.Save >> "%TEMP%\shortcut.vbs"
cscript //nologo "%TEMP%\shortcut.vbs" >nul 2>&1
del "%TEMP%\shortcut.vbs"

if exist "%SHORTCUT%" (
    echo        Desktop shortcut created.
) else (
    echo        Could not create shortcut ^(non-critical^).
)

:: ── Done ────────────────────────────────────────────────────────────────────
echo.
echo  ====================================================
echo   Installation Complete!
echo.
echo   A shortcut has been placed on your Desktop:
echo   "Rice Mill Dashboard"
echo.
echo   Double-click it to launch the dashboard.
echo   The setup wizard will guide you on first launch.
echo.
echo   NOTE: The dashboard auto-stops after 2 hours
echo   of inactivity. Simply re-open the shortcut to
echo   start it again.
echo  ====================================================
echo.

:: ── Offer to launch now ──────────────────────────────────────────────────────
set /p LAUNCH="  Launch the dashboard now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    start "" "%START_BAT%"
)

echo.
exit /b 0
