# Manual smoke test for S1 (/bootstrap 容量满仍 200) and S2 (cookie Path=/ SameSite=lax)
# Run from repo root: .\scripts\smoke_bootstrap_s1_s2.ps1
# Or copy the blocks below into PowerShell.

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8024"
$port = 8024

Write-Host "=== A) 正常模式自测（请先在另一终端启动: `$env:PYTHONPATH='src'; python -m uvicorn joygate.main:app --port $port --workers 1）===" -ForegroundColor Cyan
Write-Host ""

# A2) GET /bootstrap 检查 Set-Cookie
$r = curl.exe -s -i "$base/bootstrap" 2>&1 | Out-String
$setCookie = ($r -split "`n") | Where-Object { $_ -match "set-cookie:" }
Write-Host "Set-Cookie 行: $setCookie"
$ok = $setCookie -match "joygate_sandbox=" -and $setCookie -match "Path=/" -and $setCookie -match "SameSite=lax" -and $setCookie -match "HttpOnly" -and $setCookie -match "Max-Age="
if (-not $ok) { Write-Host "FAIL S2: Set-Cookie 应包含 joygate_sandbox=, Path=/, SameSite=lax, HttpOnly, Max-Age=" -ForegroundColor Red; exit 1 }
Write-Host "PASS S2: cookie 显式包含 Path=/ 和 SameSite=lax" -ForegroundColor Green

# A3) 用 cookie 文件 POST
Remove-Item -Path smoke_cookie.txt -ErrorAction SilentlyContinue
curl.exe -s -c smoke_cookie.txt "$base/bootstrap" | Out-Null
$post = curl.exe -s -w "`n%{http_code}" -b smoke_cookie.txt -X POST "$base/v1/incidents/report_blocked" -H "Content-Type: application/json" -d '{\"charger_id\":\"charger-001\",\"incident_type\":\"BLOCKED\"}'
$code = ($post -split "`n")[-1]
$body = ($post -split "`n")[0..($post.Length-2)] -join "`n"
if ($code -ne "200" -or $body -notmatch "incident_id") { Write-Host "FAIL A3: POST 期望 200 且 body 含 incident_id" -ForegroundColor Red; exit 1 }
Write-Host "PASS A3: POST /v1/incidents/report_blocked 返回 200 且含 incident_id" -ForegroundColor Green
Write-Host ""

Write-Host "=== B) 容量满模式自测（需先停止上面 uvicorn，再设置 JOYGATE_MAX_SANDBOXES=0 启动）===" -ForegroundColor Cyan
Write-Host "启动命令: `$env:PYTHONPATH='src'; `$env:JOYGATE_MAX_SANDBOXES='0'; python -m uvicorn joygate.main:app --port $port --workers 1" -ForegroundColor Yellow
Write-Host "启动后按回车继续..." -ForegroundColor Yellow
Read-Host

# B2) GET /bootstrap -> 200, sandbox_id null, 无 Set-Cookie
$r2 = curl.exe -s -i "$base/bootstrap" 2>&1 | Out-String
$lines = $r2 -split "`n"
$statusLine = $lines | Where-Object { $_ -match "HTTP/" } | Select-Object -First 1
$bodyStart = 0; for ($i=0;$i -lt $lines.Count;$i++) { if ($lines[$i] -eq "") { $bodyStart = $i+1; break } }
$bodyStr = $lines[$bodyStart..($lines.Count-1)] -join "`n"
if ($statusLine -notmatch "200") { Write-Host "FAIL B2: GET /bootstrap 期望 HTTP 200" -ForegroundColor Red; exit 1 }
if ($bodyStr -notmatch "sandbox_id.*null" -and $bodyStr -notmatch '"sandbox_id":\s*null') { Write-Host "FAIL B2: body 应含 sandbox_id 为 null" -ForegroundColor Red; exit 1 }
if ($r2 -match "set-cookie:\s*joygate_sandbox") { Write-Host "FAIL B2: 容量满时不应出现 Set-Cookie" -ForegroundColor Red; exit 1 }
Write-Host "PASS B2: GET /bootstrap 返回 200、sandbox_id=null、无 Set-Cookie" -ForegroundColor Green

# B3) GET /dashboard/incidents_daily -> 503 纯文本
$r3 = curl.exe -s -w "`n%{http_code}" "$base/dashboard/incidents_daily" 2>&1
$code3 = ($r3 -split "`n")[-1]
$body3 = ($r3 -split "`n")[0..($r3.Length-2)] -join "`n"
if ($code3 -ne "503") { Write-Host "FAIL B3: 期望 503" -ForegroundColor Red; exit 1 }
if ($body3 -notmatch "sandbox capacity reached") { Write-Host "FAIL B3: body 应为纯文本 sandbox capacity reached" -ForegroundColor Red; exit 1 }
Write-Host "PASS B3: GET /dashboard/incidents_daily 返回 503 且 body 为 sandbox capacity reached" -ForegroundColor Green
Write-Host ""
Write-Host "All smoke checks passed." -ForegroundColor Green
