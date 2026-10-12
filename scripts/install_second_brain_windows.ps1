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
        throw "Command failed with exit code $LASTEXITCODE: $Program $($Arguments -join ' ')"
    }
}

try {
    Set-Location $ProjectDir
    Write-Host "Configuring SecondBrain for Windows 11..." -ForegroundColor Cyan

    if (-not (Test-Path $VenvPython)) {
        $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        $Python = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            Invoke-Checked -Program $PyLauncher.Source -Arguments @("-3", "-m", "venv", ".venv")
        } elseif ($Python) {
            Invoke-Checked -Program $Python.Source -Arguments @("-m", "venv", ".venv")
        } else {
            throw "Python was not found. Install Python 3.11+ from python.org and select Add Python to PATH."
        }
    }

    if (-not (Test-Path $VenvPython)) {
        throw "Python virtual environment was not created: $VenvPython"
    }

    Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $ProjectDir "requirements.txt"))
    Invoke-Checked -Program $VenvPython -Arguments @("-m", "core.secretary.cli", "init")

    $Desktop = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($Desktop)) {
        throw "Windows Desktop folder was not found; shortcut was not created."
    }
$ShortcutPath = Join-Path $Desktop "SecondBrain.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $ProjectDir "start-second-brain-windows.cmd"
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "Start the local SecondBrain AI assistant"
    $Shortcut.Save()

    Write-Host "Runtime, data directory, and desktop shortcut are ready." -ForegroundColor Green
    exit 0
} catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
