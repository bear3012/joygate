"""
M11 最小复审：bootstrap -> POST sidecar_safety_event -> GET audit/ledger，
断言 204/200、ledger 含 audit_status 与至少 1 条 sidecar_safety_events，最新一条字段匹配。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="M11 audit ledger + sidecar_safety_event demo")
    parser.add_argument("--base_url", default="http://127.0.0.1:8050")
    parser.add_argument("--timeout_sec", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec
    session = requests.Session()

    # 第一步：GET bootstrap，确保 cookie joygate_sandbox 已设置
    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"bootstrap failed: {r_boot.status_code}", file=sys.stderr)
        sys.exit(1)
    if not session.cookies.get("joygate_sandbox"):
        print("bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        sys.exit(1)
    print("bootstrap OK, cookie set")

    # 第二步：POST /v1/audit/sidecar_safety_event
    payload = {
        "suggestion_id": "sg_001",
        "joykey": "jk_demo",
        "fleet_id": "fleetA",
        "oem_result": "SAFETY_FALLBACK",
        "fallback_reason": "low_battery",
        "observed_by": "OEM_CALLBACK",
        "observed_at": time.time(),
    }
    r_post = session.post(f"{base}/v1/audit/sidecar_safety_event", json=payload, timeout=timeout)
    if r_post.status_code != 204:
        print(f"POST sidecar_safety_event -> {r_post.status_code} {r_post.text}", file=sys.stderr)
        sys.exit(1)
    print("POST /v1/audit/sidecar_safety_event 204")

    # 第三步：GET /v1/audit/ledger
    r_ledger = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger.status_code != 200:
        print(f"GET ledger -> {r_ledger.status_code}", file=sys.stderr)
        sys.exit(1)
    try:
        data = r_ledger.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        print("ledger response not JSON", file=sys.stderr)
        sys.exit(1)
    print("GET /v1/audit/ledger 200")

    # 断言 audit_status 存在且包含约定字段
    audit_status = data.get("audit_status")
    if not isinstance(audit_status, dict):
        print("audit_status missing or not dict", file=sys.stderr)
        sys.exit(1)
    for key in ("audit_data_mode", "retention_seconds", "frame_disposition", "last_vision_audit_at"):
        if key not in audit_status:
            print(f"audit_status missing key: {key}", file=sys.stderr)
            sys.exit(1)
    print(f"audit_status: audit_data_mode={audit_status.get('audit_data_mode')} retention_seconds={audit_status.get('retention_seconds')}")

    # 断言 sidecar_safety_events 是 list 且至少 1 条
    events = data.get("sidecar_safety_events")
    if not isinstance(events, list) or len(events) < 1:
        print(f"sidecar_safety_events missing or empty: {events!r}", file=sys.stderr)
        sys.exit(1)
    latest = events[-1]
    if latest.get("joykey") != "jk_demo":
        print(f"latest joykey expected jk_demo, got {latest.get('joykey')!r}", file=sys.stderr)
        sys.exit(1)
    if latest.get("fleet_id") != "fleetA":
        print(f"latest fleet_id expected fleetA, got {latest.get('fleet_id')!r}", file=sys.stderr)
        sys.exit(1)
    if latest.get("oem_result") != "SAFETY_FALLBACK":
        print(f"latest oem_result expected SAFETY_FALLBACK, got {latest.get('oem_result')!r}", file=sys.stderr)
        sys.exit(1)
    if latest.get("observed_by") != "OEM_CALLBACK":
        print(f"latest observed_by expected OEM_CALLBACK, got {latest.get('observed_by')!r}", file=sys.stderr)
        sys.exit(1)
    if latest.get("fallback_reason") != "low_battery":
        print(f"latest fallback_reason expected low_battery, got {latest.get('fallback_reason')!r}", file=sys.stderr)
        sys.exit(1)
    sid = latest.get("sidecar_event_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        print(f"latest sidecar_event_id missing or empty: {sid!r}", file=sys.stderr)
        sys.exit(1)
    print(f"sidecar_safety_events: latest sidecar_event_id={sid} oem_result={latest.get('oem_result')} observed_by={latest.get('observed_by')}")

    # 负例：observed_at 传字符串 "123" -> 400
    r_bad1 = session.post(
        f"{base}/v1/audit/sidecar_safety_event",
        json={
            "suggestion_id": None,
            "joykey": "jk",
            "fleet_id": None,
            "oem_result": "ACCEPTED",
            "fallback_reason": None,
            "observed_by": "TELEMETRY",
            "observed_at": "123",
        },
        timeout=timeout,
    )
    print(f"negative observed_at='123' -> status={r_bad1.status_code} body={r_bad1.text}")
    if r_bad1.status_code != 400:
        print(f"expected 400, got {r_bad1.status_code}", file=sys.stderr)
        sys.exit(1)

    # 负例：observed_at 传 true（JSON boolean）-> 400
    r_bad2 = session.post(
        f"{base}/v1/audit/sidecar_safety_event",
        json={
            "suggestion_id": None,
            "joykey": "jk",
            "fleet_id": None,
            "oem_result": "ACCEPTED",
            "fallback_reason": None,
            "observed_by": "TELEMETRY",
            "observed_at": True,
        },
        timeout=timeout,
    )
    print(f"negative observed_at=true -> status={r_bad2.status_code} body={r_bad2.text}")
    if r_bad2.status_code != 400:
        print(f"expected 400, got {r_bad2.status_code}", file=sys.stderr)
        sys.exit(1)

    print("OK M11 audit ledger + sidecar_safety_event test passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
