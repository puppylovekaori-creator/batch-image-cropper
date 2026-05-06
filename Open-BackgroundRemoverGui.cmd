@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%background_remover_gui.py"

where pyw >nul 2>nul
if not errorlevel 1 (
    pyw -3.13 "%SCRIPT_PATH%" >nul 2>nul
    if not errorlevel 1 exit /b 0
    pyw -3.12 "%SCRIPT_PATH%" >nul 2>nul
    if not errorlevel 1 exit /b 0
    pyw -3.11 "%SCRIPT_PATH%" >nul 2>nul
    if not errorlevel 1 exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 -c "import sys; sys.exit(0)" >nul 2>nul
    if not errorlevel 1 (
        start "" py -3.13 "%SCRIPT_PATH%"
        exit /b 0
    )
    py -3.12 -c "import sys; sys.exit(0)" >nul 2>nul
    if not errorlevel 1 (
        start "" py -3.12 "%SCRIPT_PATH%"
        exit /b 0
    )
    py -3.11 -c "import sys; sys.exit(0)" >nul 2>nul
    if not errorlevel 1 (
        start "" py -3.11 "%SCRIPT_PATH%"
        exit /b 0
    )
)

echo Python 3.11 - 3.13 was not found.
echo Run Setup-BackgroundRemoverGui.cmd first.
pause
