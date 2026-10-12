@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" || (
  echo 无法进入项目目录：%PROJECT_DIR%
  pause
  exit /b 1
)

if not exist "scripts\install_second_brain_windows.ps1" (
  echo 找不到安装脚本 scripts\install_second_brain_windows.ps1。
  echo 请确认已完整解压项目文件后再运行。
  popd
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "scripts\install_second_brain_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo 安装没有完成，请根据上面的提示处理后重试。
  popd
  pause
  exit /b %EXIT_CODE%
)
echo.
echo 安装完成。以后双击 start-second-brain-windows.cmd 即可使用。
popd
pause
endlocal
