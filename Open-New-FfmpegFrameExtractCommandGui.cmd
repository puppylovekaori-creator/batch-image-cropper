@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%New-FfmpegFrameExtractCommandGui.pyw"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw "%SCRIPT_PATH%"
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
echo Install Python or add it to PATH.
pause
