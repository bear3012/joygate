#!/usr/bin/env python3
"""
M13.2 B3：dispatch_explain 的 ledger summary 必须有上限并能截断（需要服务）。
长 dispatch_reason_codes + context_ref 不敏感 -> tick -> ledger 中 summary<=512、含 truncated、无 context_ref 原文。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.2 B3: dispatch_explain summary cap and truncation")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK")

    r_res = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": "charger-001", "joykey": "joy_b3", "action": "HOLD"},
        timeout=timeout,
    )
    if r_res.status_code != 200:
        print(f"FAIL: reserve -> {r_res.status_code} {r_res.text}", file=sys.stderr)
        return 1
    hold_id = r_res.json().get("hold_id")

    session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "charger-001", "incident_type": "BLOCKED"},
        timeout=timeout,
    )

    # 长列表确保 summary 超 512 触发截断；context_ref 不敏感但有辨识度
    long_codes = ["OTHER"] * 300
    context_ref = "ctx_ref_should_not_leak_123"
    r_de = session.post(
        f"{base}/v1/ai/dispatch_explain",
        json={
            "hold_id": hold_id,
            "audience": "ADMIN",
            "dispatch_reason_codes": long_codes,
            "context_ref": context_ref,
        },
        timeout=timeout,
    )
    if r_de.status_code != 202:
        print(f"FAIL: POST dispatch_explain -> {r_de.status_code} {r_de.text}", file=sys.stderr)
        return 1
    ai_report_id = r_de.json().get("ai_report_id")
    print(f"POST /v1/ai/dispatch_explain 202 ai_report_id={ai_report_id}")

    r_tick = session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 2}, timeout=timeout)
    if r_tick.status_code != 200:
        print(f"FAIL: tick -> {r_tick.status_code} {r_tick.text}", file=sys.stderr)
        return 1
    if r_tick.json().get("completed", 0) < 1:
        print(f"FAIL: tick completed < 1: {r_tick.json()}", file=sys.stderr)
        return 1
    print("tick OK completed=1")

    r_ledger = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger.status_code != 200:
        print(f"FAIL: GET ledger -> {r_ledger.status_code}", file=sys.stderr)
        return 1
    decisions = r_ledger.json().get("decisions") or []
    reroute = [d for d in decisions if d.get("decision_type") == "REROUTE_SUGGESTED" and d.get("ai_report_id") == ai_report_id]
    if not reroute:
        print("FAIL: no REROUTE_SUGGESTED decision for this ai_report_id", file=sys.stderr)
        return 1
    summary = reroute[-1].get("summary") or ""
    if len(summary) > 512:
        print(f"FAIL: len(summary) must be <= 512, got {len(summary)}", file=sys.stderr)
        return 1
    if "truncated" not in summary:
        print(f"FAIL: summary should contain 'truncated', got summary len={len(summary)!r}", file=sys.stderr)
        return 1
    if context_ref in summary:
        print(f"FAIL: summary must not contain raw context_ref", file=sys.stderr)
        return 1
    print("PASS: dispatch_explain summary capped/truncated and no context_ref leak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
