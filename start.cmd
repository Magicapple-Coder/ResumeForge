@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-ResumeForge.ps1"
if errorlevel 1 pause
