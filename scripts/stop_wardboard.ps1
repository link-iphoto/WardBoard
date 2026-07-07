$ErrorActionPreference = "Stop"
. "$PSScriptRoot\wardboard_common.ps1"

Write-Host "WardBoard の終了処理を開始します。"
if (Stop-WardBoardOnConfiguredPort) {
    if (Wait-WardBoardPortClosed -TimeoutSeconds 5) {
        Write-Host "ポート $Script:WardBoardPort は解放されています。"
        exit 0
    }
    Write-Host "ポート $Script:WardBoardPort がまだ使用中です。"
    exit 1
}

exit 1
