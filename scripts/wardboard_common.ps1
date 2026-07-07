$ErrorActionPreference = "Stop"

$Script:WardBoardRoot = Split-Path -Parent $PSScriptRoot
$Script:WardBoardConfigPath = Join-Path $Script:WardBoardRoot "wardboard_config.json"

if (-not (Test-Path -LiteralPath $Script:WardBoardConfigPath)) {
    throw "wardboard_config.json が見つかりません。"
}

$Script:WardBoardConfig = Get-Content -LiteralPath $Script:WardBoardConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$Script:WardBoardHost = [string]$Script:WardBoardConfig.host
$Script:WardBoardPort = [int]$Script:WardBoardConfig.port
$Script:WardBoardUrl = "http://{0}:{1}" -f $Script:WardBoardHost, $Script:WardBoardPort

function Get-WardBoardPortOwner {
    $conn = Get-NetTCPConnection -LocalPort $Script:WardBoardPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $process) {
        return [pscustomobject]@{
            ProcessId = $conn.OwningProcess
            Name = ""
            CommandLine = ""
        }
    }

    return [pscustomobject]@{
        ProcessId = [int]$process.ProcessId
        Name = [string]$process.Name
        CommandLine = [string]$process.CommandLine
    }
}

function Test-WardBoardProcess {
    param([Parameter(Mandatory=$true)]$Owner)

    $name = ([string]$Owner.Name).ToLowerInvariant()
    $commandLine = ([string]$Owner.CommandLine).ToLowerInvariant()
    $root = $Script:WardBoardRoot.ToLowerInvariant().Replace("/", "\")
    $commandLineNormalized = $commandLine.Replace("/", "\")

    if ($name -notmatch "python") {
        return $false
    }

    if ($commandLineNormalized.Contains($root) -and $commandLineNormalized.Contains("src\app.py")) {
        return $true
    }

    if ($commandLineNormalized.Contains("src\app.py")) {
        return $true
    }

    if ($commandLine.Contains("import app") -and $commandLine.Contains("app.run")) {
        return $true
    }

    return $false
}

function Wait-WardBoardPortClosed {
    param([int]$TimeoutSeconds = 8)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-WardBoardPortOwner)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Wait-WardBoardPortOpen {
    param([int]$TimeoutSeconds = 15)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-WardBoardPortOwner) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Wait-WardBoardHttpReady {
    param([int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $timelineUrl = "$Script:WardBoardUrl/timeline"
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $timelineUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Stop-WardBoardOnConfiguredPort {
    $owner = Get-WardBoardPortOwner
    if (-not $owner) {
        return $true
    }

    if (-not (Test-WardBoardProcess -Owner $owner)) {
        Write-Host "ポート $Script:WardBoardPort は別のアプリで使用中です。"
        Write-Host "WardBoard を起動できません。"
        Write-Host "使用中のプロセスを確認してください。"
        Write-Host "PID: $($owner.ProcessId)"
        Write-Host "Process: $($owner.Name)"
        Write-Host "CommandLine: $($owner.CommandLine)"
        return $false
    }

    Write-Host "前回の WardBoard プロセスを終了します。PID: $($owner.ProcessId)"
    Stop-Process -Id $owner.ProcessId -Force -ErrorAction Stop
    if (-not (Wait-WardBoardPortClosed -TimeoutSeconds 8)) {
        Write-Host "ポート $Script:WardBoardPort を解放できませんでした。"
        return $false
    }
    return $true
}

function Find-WardBoardBrowser {
    $commands = @(
        "msedge.exe",
        "chrome.exe"
    )
    foreach ($command in $commands) {
        $found = Get-Command $command -ErrorAction SilentlyContinue
        if ($found) {
            return $found.Source
        }
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $knownPaths = @(
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe")
    )
    foreach ($candidate in $knownPaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Wait-WardBoardBrowserClosed {
    param(
        [Parameter(Mandatory=$true)][string]$ProfileDir,
        [Parameter(Mandatory=$true)][System.Diagnostics.Process]$BrowserProcess
    )

    $profileNeedle = $ProfileDir.ToLowerInvariant()
    while ($true) {
        $profileProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileNeedle)
            }

        if (-not $profileProcesses) {
            if ($BrowserProcess.HasExited) {
                return
            }
        }

        Start-Sleep -Seconds 1
    }
}
