#!/usr/bin/env python3
"""
路由层入口字段统一限长/防污染验货：每个关键入口 1 个负例（超长/前后空白→400）、1 个正例（最小可跑通→200/204/202）。
仅用标准库（urllib），支持 --base_url。失败 exit(1)。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
import http.cookiejar

BASE_URL_DEFAULT = "http://127.0.0.1:8000"


def _req(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 10.0, opener: urllib.request.OpenerDirector | None = None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        if opener is not None:
            r = opener.open(req, timeout=timeout)
        else:
            r = urllib.request.urlopen(req, timeout=timeout)
        with r:
            return r.getcode(), r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _detail(text: str) -> str:
    try:
        return (json.loads(text) or {}).get("detail", "") or ""
    except Exception:
        return text or ""


def main() -> int:
    p = argparse.ArgumentParser(description="Route input limits: negative→400, positive→200/204/202")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT)
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    fails = 0
    # Cookie 保持：bootstrap 会 Set-Cookie joygate_sandbox，后续 /v1/* 需要带 cookie
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # bootstrap
    code, _ = _req("GET", f"{base}/bootstrap", timeout=timeout, opener=opener)
    if code != 200:
        print(f"FAIL: bootstrap {code}")
        return 1
    print("bootstrap OK")

    # 1) incidents/report_blocked: charger_id 超长 => 400
    code, text = _req("POST", f"{base}/v1/incidents/report_blocked", body={"charger_id": "x" * 65, "incident_type": "BLOCKED"}, timeout=timeout, opener=opener)
    if code != 400 or "invalid charger_id" not in _detail(text):
        print(f"FAIL: report_blocked charger_id 65 expected 400, got {code} detail={_detail(text)}")
        fails += 1
    else:
        print(f"OK: report_blocked charger_id 65 -> {code} invalid charger_id")

    # 1b) report_blocked 正例 => 200 incident_id（后续 witness/vision_audit 复用）
    code, text = _req("POST", f"{base}/v1/incidents/report_blocked", body={"charger_id": "charger-001", "incident_type": "BLOCKED"}, timeout=timeout, opener=opener)
    try:
        incident_id = (json.loads(text) or {}).get("incident_id") if code == 200 else None
    except Exception:
        incident_id = None
    if code != 200:
        print(f"FAIL: report_blocked positive expected 200, got {code} {text}")
        fails += 1
    else:
        print(f"OK: report_blocked positive -> {code} incident_id={incident_id!r}")

    # 2) witness/respond: points_event_id 超长 => 400（需要 incident_id，用上一步的）
    if not incident_id:
        incident_id = "inc-fallback"
    code, text = _req(
        "POST", f"{base}/v1/witness/respond",
        body={"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "OCCUPIED", "points_event_id": "p" * 65},
        headers={"X-JoyKey": "w1"}, timeout=timeout, opener=opener,
    )
    if code != 400 or "invalid points_event_id" not in _detail(text):
        print(f"FAIL: witness/respond points_event_id 65 expected 400, got {code} detail={_detail(text)}")
        fails += 1
    else:
        print(f"OK: witness/respond points_event_id 65 -> {code} invalid points_event_id")

    # 2b) witness/respond 正例 => 204
    code, text = _req(
        "POST", f"{base}/v1/witness/respond",
        body={"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "FREE", "points_event_id": "pe-min"},
        headers={"X-JoyKey": "w1"}, timeout=timeout, opener=opener,
    )
    if code != 204:
        print(f"FAIL: witness/respond positive expected 204, got {code} {text}")
        fails += 1
    else:
        print(f"OK: witness/respond positive -> {code}")

    # 3) segment_respond: segment_id 超长 => 400
    code, text = _req(
        "POST", f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w2"},
        body={"segment_id": "x" * 65, "segment_state": "PASSABLE", "points_event_id": "seg-pe-1"},
        timeout=timeout, opener=opener,
    )
    if code != 400 or "invalid segment_id" not in _detail(text):
        print(f"FAIL: segment_respond segment_id 65 expected 400, got {code} detail={_detail(text)}")
        fails += 1
    else:
        print(f"OK: segment_respond segment_id 65 -> {code} invalid segment_id")

    # 3b) segment_respond 正例 => 204
    code, text = _req(
        "POST", f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w2"},
        body={"segment_id": "cell_1_1", "segment_state": "PASSABLE", "points_event_id": "seg-pe-2"},
        timeout=timeout, opener=opener,
    )
    if code != 204:
        print(f"FAIL: segment_respond positive expected 204, got {code} {text}")
        fails += 1
    else:
        print(f"OK: segment_respond positive -> {code}")

    # 4) work_orders/report: work_order_id 超长 => 400
    code, text = _req(
        "POST", f"{base}/v1/work_orders/report",
        body={"work_order_id": "x" * 65, "work_order_status": "OPEN", "event_occurred_at": 1e9},
        timeout=timeout, opener=opener,
    )
    if code != 400 or "invalid work_order_id" not in _detail(text):
        print(f"FAIL: work_orders/report work_order_id 65 expected 400, got {code} detail={_detail(text)}")
        fails += 1
    else:
        print(f"OK: work_orders/report work_order_id 65 -> {code} invalid work_order_id")

    # 4b) work_orders/report 正例 => 204
    code, text = _req(
        "POST", f"{base}/v1/work_orders/report",
        body={"work_order_id": "wo-min", "work_order_status": "OPEN", "event_occurred_at": 1e9},
        timeout=timeout, opener=opener,
    )
    if code != 204:
        print(f"FAIL: work_orders/report positive expected 204, got {code} {text}")
        fails += 1
    else:
        print(f"OK: work_orders/report positive -> {code}")

    # 5) ai/vision_audit: snapshot_ref 超长 => 400；正例用同一 incident_id
    vid = incident_id or "vi-1"
    code, text = _req(
        "POST", f"{base}/v1/ai/vision_audit",
        body={"incident_id": vid, "snapshot_ref": "s" * 65},
        timeout=timeout, opener=opener,
    )
    if code != 400 or "invalid snapshot_ref" not in _detail(text):
        print(f"FAIL: ai/vision_audit snapshot_ref 65 expected 400, got {code} detail={_detail(text)}")
        fails += 1
    else:
        print(f"OK: ai/vision_audit snapshot_ref 65 -> {code} invalid snapshot_ref")

    # 5b) ai/vision_audit 正例 => 202
    code, text = _req(
        "POST", f"{base}/v1/ai/vision_audit",
        body={"incident_id": vid},
        timeout=timeout, opener=opener,
    )
    if code != 202:
        print(f"FAIL: ai/vision_audit positive expected 202, got {code} {text}")
        fails += 1
    else:
        print(f"OK: ai/vision_audit positive -> {code}")

    if fails:
        print(f"FAIL: {fails} case(s) failed")
        return 1
    print("PASS: all route input limit checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
