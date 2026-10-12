@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" || (
  echo 无法进入项目目录：%PROJECT_DIR%
  pause
  exit /b 1
)

if not exist "scripts\start_second_brain_windows.ps1" (
  echo 找不到启动脚本 scripts\start_second_brain_windows.ps1。
  echo 请确认已完整解压项目文件后再运行。
  popd
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "scripts\start_second_brain_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo 第二大脑启动失败，请查看上面的提示和 data\server-windows-error.log。
  popd
  pause
  exit /b %EXIT_CODE%
)
echo.
echo 浏览器已经打开。按任意键关闭此启动窗口；服务会继续在后台运行。
popd
pause
endlocal
