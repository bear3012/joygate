# 验证 webhook 订阅数上限 50：新沙盒创建 51 个 enabled 订阅，第 51 次应返回 400
# 前提：uvicorn 已用最新代码重启（例如 --port 8040）
# 使用：.\scripts\run_51_webhook_subscriptions_limit.ps1 [base_url]
# 默认 base_url = http://127.0.0.1:8040

param([string]$base = "http://127.0.0.1:8040")

$boot = (curl.exe -s -i "$base/bootstrap") -join "`n"
$sid = [regex]::Match($boot, 'joygate_sandbox=([^;]+)').Groups[1].Value
if (-not $sid) { Write-Error "bootstrap did not return joygate_sandbox cookie"; exit 1 }
$cookie = "joygate_sandbox=$sid"
$body = '{"target_url":"http://127.0.0.1:9001/w","event_types":["INCIDENT_CREATED"],"secret":null,"is_enabled":true}'
$reqFile = Join-Path (Split-Path -Parent $PSScriptRoot) "req_51sub.json"
[System.IO.File]::WriteAllText($reqFile, $body, [System.Text.UTF8Encoding]::new($false))

$lastCode = ""
$lastOut = ""
1..51 | ForEach-Object {
  $r = curl.exe -s -w "`n%{http_code}" -b $cookie -H "Content-Type: application/json" --data-binary "@$reqFile" "$base/v1/webhooks/subscriptions"
  $parts = $r -split "`n"
  $lastOut = $parts[0]
  $lastCode = $parts[-1]
}

"51st http_code => $lastCode"
"51st body => $lastOut"
if ($lastCode -eq "400") {
  "OK: 51st subscription correctly rejected with 400."
  exit 0
}
exit 1
