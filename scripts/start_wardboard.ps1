param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\wardboard_common.ps1"

$logDir = Join-Path $Script:WardBoardRoot "logs"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$launcherLog = Join-Path $logDir "wardboard_launcher.log"
$serverOutLog = Join-Path $logDir "wardboard_server_stdout.log"
$serverErrLog = Join-Path $logDir "wardboard_server_stderr.log"

function Write-LauncherLog {
    param([Parameter(Mandatory=$true)][string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $launcherLog -Value $line -Encoding UTF8
    if ($Dev) {
        Write-Host $Message
    }
}

Write-LauncherLog "WardBoard launcher started."
Write-Host "WardBoard を起動します。URL: $Script:WardBoardUrl"

if (-not (Stop-WardBoardOnConfiguredPort)) {
    Write-LauncherLog "Port check failed. WardBoard was not started."
    exit 1
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "python が見つかりません。Python をインストールするか、PATH を確認してください。"
    Write-LauncherLog "python command was not found."
    exit 1
}

$serverArgs = @("src\app.py")
$serverStartInfo = @{
    FilePath = $python.Source
    ArgumentList = $serverArgs
    WorkingDirectory = $Script:WardBoardRoot
    PassThru = $true
    RedirectStandardOutput = $serverOutLog
    RedirectStandardError = $serverErrLog
}

if ($Dev) {
    Write-Host "開発用起動: サーバーログ用のPythonプロセスを起動します。"
} else {
    $serverStartInfo.WindowStyle = "Hidden"
}

$serverProcess = Start-Process @serverStartInfo
Write-LauncherLog "Server process started. PID: $($serverProcess.Id)"

try {
    if (-not (Wait-WardBoardPortOpen -TimeoutSeconds 15)) {
        Write-Host "WardBoard サーバーの起動を確認できませんでした。"
        Write-LauncherLog "Server port did not open."
        if (-not $serverProcess.HasExited) {
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }
    if (-not (Wait-WardBoardHttpReady -TimeoutSeconds 20)) {
        Write-Host "WardBoard サーバーの応答を確認できませんでした。"
        Write-LauncherLog "Server HTTP readiness check failed."
        if (-not $serverProcess.HasExited) {
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }
    Write-LauncherLog "Server is ready at $Script:WardBoardUrl."

    $browser = Find-WardBoardBrowser
    if (-not $browser) {
        Write-Host "Microsoft Edge または Google Chrome が見つかりません。"
        Write-Host "ブラウザで次のURLを開いてください: $Script:WardBoardUrl"
        Write-Host "終了するときは stop_wardboard.bat を実行してください。"
        Write-LauncherLog "No supported browser was found."
        exit 0
    }

    $profileDir = Join-Path $env:TEMP "WardBoardBrowserProfile-$Script:WardBoardPort"
    if (-not (Test-Path -LiteralPath $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir | Out-Null
    }

    $browserArgs = @(
        "--user-data-dir=$profileDir",
        "--app=$Script:WardBoardUrl"
    )
    $browserProcess = Start-Process -FilePath $browser -ArgumentList $browserArgs -PassThru
    Write-LauncherLog "Browser process started. PID: $($browserProcess.Id). Path: $browser"
    Write-Host "WardBoard ブラウザを開きました。ウィンドウを閉じるとサーバーも終了します。"

    Wait-WardBoardBrowserClosed -ProfileDir $profileDir -BrowserProcess $browserProcess
    Write-LauncherLog "Browser window closed."
}
finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Write-Host "WardBoard サーバーを終了します。"
        Write-LauncherLog "Stopping server process. PID: $($serverProcess.Id)"
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        Wait-WardBoardPortClosed -TimeoutSeconds 8 | Out-Null
    }
    Write-LauncherLog "WardBoard launcher finished."
}
