$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

Set-Location $ProjectDir
Write-Host "正在为 Windows 11 配置第二大脑…" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    $Python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        & $PyLauncher.Source -3 -m venv ".venv"
    } elseif ($Python) {
        & $Python.Source -m venv ".venv"
    } else {
        Write-Host "未找到 Python。请先从 python.org 安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。" -ForegroundColor Yellow
        exit 2
    }
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectDir "requirements.txt")
& $VenvPython -m core.secretary.cli init

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "第二大脑.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $ProjectDir "启动第二大脑-Windows.cmd"
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "启动本地第二大脑 AI 助理"
$Shortcut.Save()

Write-Host "运行环境、数据目录和桌面快捷方式已准备完成。" -ForegroundColor Green
