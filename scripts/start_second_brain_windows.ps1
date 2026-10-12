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
        Write-Host "尚未安装项目运行环境。请先双击“安装第二大脑-Windows.cmd”。" -ForegroundColor Yellow
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
        Write-Host "正在启动第二大脑…"
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
            Write-Host "服务未能在 12 秒内启动。错误日志：$StderrLog" -ForegroundColor Red
            if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 20 }
            exit 1
        }
    }

    Write-Host "第二大脑已运行：$BrowserUrl" -ForegroundColor Green
    if (-not $LocalOnly) {
        Write-Host "已允许可信局域网内的已配对手机连接；首次运行时请允许 Windows 防火墙的专用网络访问。"
    }
    Start-Process $BrowserUrl
    exit 0
} catch {
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
