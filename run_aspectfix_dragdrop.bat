@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%aspectfix_dragdrop_gui.py"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%SCRIPT_PATH%"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%SCRIPT_PATH%"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    start "" py -3 "%SCRIPT_PATH%"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" python "%SCRIPT_PATH%"
    exit /b 0
)

echo Python Launcher or Python was not found.
echo Install Python, then run: py -3 -m pip install -r requirements_aspectfix.txt
pause
