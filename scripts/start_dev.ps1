# JoyGate 开发启动入口（单 worker，不踩多进程坑）
# 用法：在项目根目录执行 .\scripts\start_dev.ps1 或 cd scripts; .\start_dev.ps1
$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) { (Resolve-Path (Join-Path $PSScriptRoot "..")).Path } else { Get-Location }
Set-Location $Root

$env:PYTHONPATH = "src"
$Port = 8000
$HostAddr = "127.0.0.1"

Write-Host "=== JoyGate dev server (workers=1, no --reload) ===" -ForegroundColor Cyan
Write-Host "  PYTHONPATH=$env:PYTHONPATH"
Write-Host "  1) 必须先 GET /bootstrap 拿到 cookie，再调用 POST /v1/*"
Write-Host "  2) 修改环境变量后必须重启本进程"
Write-Host "  3) 启动: http://${HostAddr}:${Port}"
Write-Host ""

& "$Root\.venv\Scripts\python.exe" -m uvicorn joygate.main:app --host $HostAddr --port $Port --workers 1
