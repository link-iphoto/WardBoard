@echo off
cd /d "%~dp0"

echo WardBoard を開発用モードで起動します...
echo URL: http://127.0.0.1:58731

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_wardboard.ps1" -Dev

pause
