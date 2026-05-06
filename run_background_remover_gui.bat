@echo off
setlocal
cd /d "%~dp0"

for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import sys; print(sys.executable)" >nul 2>&1
    if not errorlevel 1 (
        py -%%V "%~dp0background_remover_gui.py"
        exit /b
    )
)

python "%~dp0background_remover_gui.py"
exit /b
