@echo off
setlocal EnableExtensions
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" || (
  echo ERROR: Cannot open project directory: %PROJECT_DIR%
  pause
  exit /b 1
)

if not exist "scripts\start_second_brain_windows.ps1" (
  echo ERROR: Missing scripts\start_second_brain_windows.ps1
  echo Ensure the project archive was fully extracted, then try again.
  popd
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "scripts\start_second_brain_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Review the message above and data\server-windows-error.log.
  popd
  pause
  exit /b %EXIT_CODE%
)
echo.
echo Browser opened. Press any key to close this window; the service keeps running.
popd
pause
endlocal
