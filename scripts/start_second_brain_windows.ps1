param(
    [switch]$LocalOnly
)

try {
    $ErrorActionPreference = "Stop"
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    $DataDir = Join-Path $ProjectDir "data"
    $StdoutLog = Join-Path $DataDir "server-windows.log"
    $StderrLog = Join-Path $DataDir "server-windows-error.log"
    $Port = if ($env:SECOND_BRAIN_PORT) { [int]$env:SECOND_BRAIN_PORT } else { 8765 }
    $HostAddress = if ($LocalOnly) { "127.0.0.1" } else { "0.0.0.0" }
    $BrowserUrl = "http://127.0.0.1:$Port"

    if (-not (Test-Path $Python)) {
        Write-Host "Runtime is not installed. Run install-second-brain-windows.cmd first." -ForegroundColor Yellow
        exit 2
    }

    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null

    function Test-SecondBrain {
        try {
            $response = Invoke-RestMethod -Uri "$BrowserUrl/api/health" -TimeoutSec 2
            return $response.ok -eq $true
        } catch {
            return $false
        }
    }

    if (-not (Test-SecondBrain)) {
        Write-Host "Starting SecondBrain..."
        $arguments = @(
            "-m", "uvicorn", "core.secretary.app:app",
            "--app-dir", ('"' + $ProjectDir + '"'),
            "--host", $HostAddress,
            "--port", $Port.ToString()
        )
        Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $ProjectDir `
            -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog | Out-Null

        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Milliseconds 400
            if (Test-SecondBrain) {
                $ready = $true
                break
            }
        }
        if (-not $ready) {
            Write-Host "Service did not start within 12 seconds. Error log: $StderrLog" -ForegroundColor Red
            if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 20 }
            exit 1
        }
    }

    Write-Host "SecondBrain is running: $BrowserUrl" -ForegroundColor Green
    if (-not $LocalOnly) {
        Write-Host "Paired phones on a trusted LAN can connect. Allow Python through Windows Firewall on private networks when prompted."
    }
    Start-Process $BrowserUrl
    exit 0
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
