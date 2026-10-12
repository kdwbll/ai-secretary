$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令执行失败（退出码 $LASTEXITCODE）：$Program $($Arguments -join ' ')"
    }
}

try {
    Set-Location $ProjectDir
    Write-Host "正在为 Windows 11 配置第二大脑…" -ForegroundColor Cyan

    if (-not (Test-Path $VenvPython)) {
        $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        $Python = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            Invoke-Checked -Program $PyLauncher.Source -Arguments @("-3", "-m", "venv", ".venv")
        } elseif ($Python) {
            Invoke-Checked -Program $Python.Source -Arguments @("-m", "venv", ".venv")
        } else {
            throw "未找到 Python。请先从 python.org 安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。"
        }
    }

    if (-not (Test-Path $VenvPython)) {
        throw "Python 虚拟环境创建失败：$VenvPython"
    }

    Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $ProjectDir "requirements.txt"))
    Invoke-Checked -Program $VenvPython -Arguments @("-m", "core.secretary.cli", "init")

    $Desktop = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($Desktop)) {
        throw "无法确定 Windows 桌面目录，未创建快捷方式。"
    }
    $ShortcutPath = Join-Path $Desktop "第二大脑.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $ProjectDir "启动第二大脑-Windows.cmd"
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "启动本地第二大脑 AI 助理"
    $Shortcut.Save()

    Write-Host "运行环境、数据目录和桌面快捷方式已准备完成。" -ForegroundColor Green
    exit 0
} catch {
    Write-Host "安装失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
