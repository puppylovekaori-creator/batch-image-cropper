@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0Setup-BackgroundRemoverGui.ps1"
if errorlevel 1 pause
