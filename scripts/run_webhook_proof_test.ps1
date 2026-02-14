# 最小可证明测试：webhook 订阅 + 事件触发 + deliveries 校验
# 前提：服务 http://127.0.0.1:8010 已启动；webhook 接收器 127.0.0.1:9001 已启动（见下方 3.1）
# 使用：先在一个终端运行 3.1 的 Python 接收器，再在本机运行本脚本。

$base = "http://127.0.0.1:8010"
$ErrorActionPreference = "Stop"

# (1) bootstrap 拿 cookie（用 -b 传 cookie，避免 cookie 文件在 Windows 下不写入）
$boot = curl.exe -s "$base/bootstrap"
$sid = ($boot | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('sandbox_id',''))")
if (-not $sid) { Write-Error "bootstrap failed: $boot"; exit 1 }
Write-Host "sandbox_id=$sid"

# (2) 创建两个订阅（用 JSON 文件避免 PowerShell 转义）
$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_sub_no_secret.json" "$base/v1/webhooks/subscriptions"
Write-Host ""
curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_sub_with_secret.json" "$base/v1/webhooks/subscriptions"
Write-Host ""

# (3) report_blocked
$incJson = curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_report_blocked.json" "$base/v1/incidents/report_blocked"
Write-Host "report_blocked: $incJson"
$INC_ID = ($incJson | python -c "import json,sys; print(json.load(sys.stdin).get('incident_id',''))")
Write-Host "INC_ID=$INC_ID"

# (4) update_status（动态生成 body）
$statusBody = '{"incident_id":"' + $INC_ID + '","incident_status":"ESCALATED"}'
Set-Content -Path "$root/req_update_status.json" -Value $statusBody -NoNewline -Encoding utf8
curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_update_status.json" "$base/v1/incidents/update_status"
Write-Host "update_status done"

# (5) vision_audit
$visionBody = '{"incident_id":"' + $INC_ID + '"}'
Set-Content -Path "$root/req_vision_audit.json" -Value $visionBody -NoNewline -Encoding utf8
curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_vision_audit.json" "$base/v1/ai_jobs/vision_audit"
Write-Host "vision_audit done"

# (6) tick
curl.exe -s -b "joygate_sandbox=$sid" -H "Content-Type: application/json" --data-binary "@$root/req_tick.json" "$base/v1/ai_jobs/tick"
Write-Host "tick done"

# (7) 验证 deliveries
Write-Host "--- /v1/webhooks/deliveries ---"
curl.exe -s -b "joygate_sandbox=$sid" "$base/v1/webhooks/deliveries"
Write-Host ""
