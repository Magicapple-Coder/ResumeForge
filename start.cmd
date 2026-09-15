@echo off
setlocal
rem %* forwards -BackendPort / -FrontendPort / -NoBrowser to the launcher.
rem Use the space-separated form: -BackendPort=8010 does not bind with -File.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-ResumeForge.ps1" %*
if errorlevel 1 pause
