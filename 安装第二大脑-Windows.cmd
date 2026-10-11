@echo off
chcp 65001 >nul
setlocal
set "PROJECT_DIR=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%scripts\install_second_brain_windows.ps1"
if errorlevel 1 (
  echo.
  echo 安装没有完成，请根据上面的提示处理后重试。
  pause
  exit /b 1
)
echo.
echo 安装完成。以后双击“启动第二大脑-Windows.cmd”即可使用。
pause
endlocal
