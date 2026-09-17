@echo off
rem ResumeForge uninstaller. Keeps your data unless you pass -Purge.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Uninstall-ResumeForge.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo Uninstall exited with code %EXITCODE%. Read the messages above.
)
pause
exit /b %EXITCODE%
