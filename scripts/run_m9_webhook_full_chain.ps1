# M9 Outbound Webhooks 全链路一键测试（可复现）
# 前提：终端 1 已启动 uvicorn --port 8040；终端 2 已启动 webhook 接收器 127.0.0.1:9001
# 使用：在项目根目录执行 .\scripts\run_m9_webhook_full_chain.ps1
# 若 RUN_LOG 中出现 Get-ChildItem Env: 报错，请用 powershell -NoProfile -File .\scripts\run_m9_webhook_full_chain.ps1 执行，避免运行环境注入污染输出。
#
# 本地 demo：订阅 target_url 为 http://127.0.0.1:9001，需在启动 uvicorn 的终端显式开启：
#   $env:JOYGATE_WEBHOOK_ALLOW_HTTP="1"
#   $env:JOYGATE_WEBHOOK_ALLOW_LOCALHOST="1"
#   $env:PYTHONPATH="src"
#   python -m uvicorn joygate.main:app --host 127.0.0.1 --port 8040 --workers 1

$base = "http://127.0.0.1:8040"

# (0) OpenAPI 先验：必须包含关键 path
curl.exe -s "$base/openapi.json" | Select-String -Pattern `
  "/v1/webhooks/subscriptions", "/v1/webhooks/deliveries", "/v1/ai_jobs", "/v1/incidents/update_status"

# (1) bootstrap 拿 cookie（从 Set-Cookie 提取 joygate_sandbox）
$boot = (curl.exe -s -i "$base/bootstrap") -join "`n"
$sid  = [regex]::Match($boot, 'joygate_sandbox=([^;]+)').Groups[1].Value
if (-not $sid) { throw "bootstrap did not return joygate_sandbox cookie" }
$cookie = "joygate_sandbox=$sid"
"COOKIE => $cookie"

$reqBodyFile = Join-Path (Split-Path -Parent $PSScriptRoot) "req_m9_chain.json"

function PostJson($path, $obj) {
  $url = "$base$path"
  $json = $obj | ConvertTo-Json -Compress -Depth 10
  [System.IO.File]::WriteAllText($reqBodyFile, $json, [System.Text.UTF8Encoding]::new($false))
  curl.exe -s -b $cookie -H "Content-Type: application/json" --data-binary "@$reqBodyFile" $url
}

function PostJsonStatus($path, $obj) {
  $url = "$base$path"
  $json = $obj | ConvertTo-Json -Compress -Depth 10
  [System.IO.File]::WriteAllText($reqBodyFile, $json, [System.Text.UTF8Encoding]::new($false))
  curl.exe -s -o $null -w "%{http_code}`n" -b $cookie -H "Content-Type: application/json" --data-binary "@$reqBodyFile" $url
}

# (2) 创建订阅：secret=null（不签名）
PostJson "/v1/webhooks/subscriptions" @{
  target_url = "http://127.0.0.1:9001/webhook"
  event_types = @("INCIDENT_CREATED", "INCIDENT_STATUS_CHANGED", "AI_JOB_STATUS_CHANGED")
  secret = $null
  is_enabled = $true
}
""

# (3) 创建订阅：secret="s3cr3t"（签名）
PostJson "/v1/webhooks/subscriptions" @{
  target_url = "http://127.0.0.1:9001/webhook"
  event_types = @("INCIDENT_CREATED", "INCIDENT_STATUS_CHANGED", "AI_JOB_STATUS_CHANGED")
  secret = "s3cr3t"
  is_enabled = $true
}
""

# (4) report_blocked -> incident_id
$incJson = PostJson "/v1/incidents/report_blocked" @{
  charger_id = "charger-001"
  incident_type = "BLOCKED"
  snapshot_ref = "snap_demo"
  evidence_refs = @("ev:anchor:demo1")
}
"INCIDENT => $incJson"
$incId = ($incJson | ConvertFrom-Json).incident_id
if (-not $incId) { throw "missing incident_id" }
"INC_ID => $incId"
""

# (5) update_status（期望 204，用 curl -w 经 cmd 重定向到文件再读，保证硬打印 204）
$updateBody = @{ incident_id = $incId; incident_status = "ESCALATED" } | ConvertTo-Json -Compress -Depth 5
[System.IO.File]::WriteAllText($reqBodyFile, $updateBody, [System.Text.UTF8Encoding]::new($false))
$statusFile = Join-Path (Split-Path -Parent $PSScriptRoot) "req_m9_update_status.txt"
$updateUrl = "$base/v1/incidents/update_status"
cmd /c "curl.exe -s -o NUL -w ""%{http_code}"" -b ""$cookie"" -H ""Content-Type: application/json"" --data-binary ""@$reqBodyFile"" ""$updateUrl"" > ""$statusFile"""
$updateCode = Get-Content -Path $statusFile -Raw -ErrorAction SilentlyContinue
if (-not $updateCode) { $updateCode = "" }
"update_status http_code => $updateCode"
""

# (5b) 重复触发同一事件：再次 update_status 相同状态，验证 deliveries 不翻倍（create_webhook_delivery_if_absent）
cmd /c "curl.exe -s -o NUL -w ""%{http_code}"" -b ""$cookie"" -H ""Content-Type: application/json"" --data-binary ""@$reqBodyFile"" ""$updateUrl"" > NUL"
"update_status (repeat same) done"
""

# (6) create vision audit job
PostJson "/v1/ai_jobs/vision_audit" @{ incident_id = $incId }
""

# (7) tick
PostJson "/v1/ai_jobs/tick" @{ max_jobs = 1 }
""

Start-Sleep -Seconds 1

# (8) deliveries
$del = curl.exe -s -b $cookie "$base/v1/webhooks/deliveries"
"DELIVERIES => $del"
""
