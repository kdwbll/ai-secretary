@echo off
chcp 65001 >nul
setlocal
set "PROJECT_DIR=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%scripts\start_second_brain_windows.ps1"
if errorlevel 1 (
  echo.
  echo 第二大脑启动失败，请查看上面的提示和 data\server-windows-error.log。
  pause
)
endlocal
