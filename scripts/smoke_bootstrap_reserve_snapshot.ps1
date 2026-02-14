# Smoke: bootstrap -> reserve -> snapshot; assert holds[0] has 4 ext fields.
$ErrorActionPreference = "Stop"
$Base = "http://127.0.0.1:8000"
$Root = "D:\joykeep\joygate\joygate_hackathon"
Set-Location $Root

# 删除旧文件
Remove-Item -Path "cookies.txt" -ErrorAction SilentlyContinue
Remove-Item -Path "reserve_body.json" -ErrorAction SilentlyContinue

Write-Host "=== (a) GET /bootstrap ==="
$bootstrapOut = & { $ErrorActionPreference = "Continue"; curl.exe -s -i -c cookies.txt "$Base/bootstrap" } | Out-String
Write-Host $bootstrapOut

Write-Host ""
Write-Host "=== (b) Write reserve_body.json (UTF-8 no BOM) ==="
$jsonContent = '{"resource_type":"charger","resource_id":"charger-001","joykey":"smoke_joykey","action":"HOLD"}'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("$Root\reserve_body.json", $jsonContent, $utf8NoBom)
Write-Host "Done. Content: $jsonContent"

Write-Host ""
Write-Host "=== (c) POST /v1/reserve ==="
$reserveOut = & { $ErrorActionPreference = "Continue"; curl.exe -s -i -b cookies.txt -X POST "$Base/v1/reserve" -H "Content-Type: application/json" --data-binary "@reserve_body.json" } | Out-String
Write-Host $reserveOut

Write-Host ""
Write-Host "=== (d) GET /v1/snapshot ==="
$snapshotBody = & { $ErrorActionPreference = "Continue"; curl.exe -s -b cookies.txt "$Base/v1/snapshot" } | Out-String
Write-Host $snapshotBody

Write-Host ""
Write-Host "=== Assertions (holds length + holds[0] 4 ext fields) ==="
try {
    $snap = $snapshotBody | ConvertFrom-Json
    $holds = @($snap.holds)
    if ($holds.Count -lt 1) {
        Write-Host "FAIL: holds empty"
        exit 1
    }
    $h0 = $holds[0]
    $actualKeys = @($h0.PSObject.Properties.Name)
    Write-Host "holds[0] actual keys: $($actualKeys -join ', ')"
    $required = @("is_priority_compensated", "compensation_reason", "queue_position_drift", "incident_id")
    $missing = @()
    foreach ($k in $required) {
        if ($k -notin $actualKeys) {
            $missing += $k
        }
    }
    if ($missing.Count -gt 0) {
        Write-Host "FAIL: holds[0] missing keys: $($missing -join ', ')"
        exit 1
    }
    Write-Host "PASS: holds.Count>=1, holds[0] has is_priority_compensated, compensation_reason, queue_position_drift, incident_id"
} catch {
    Write-Host "FAIL: $($_.Exception.Message)"
    exit 1
}
