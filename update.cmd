@echo off
rem ResumeForge updater. Updates program files only; data\ and .env are kept.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Update-ResumeForge.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo Update failed with exit code %EXITCODE%. Read the messages above.
) else (
  echo Done. Start the app again with start.cmd.
)
pause
exit /b %EXITCODE%
