#!/usr/bin/env python3
"""
M13.1 T4：apply_policy_suggestion 归属与状态校验。
1) policy_suggest 不 tick 直接 apply -> 409 (not completed)
2) tick 后再 apply -> 202
3) 用 DISPATCH_EXPLAIN 的 ai_report_id 去 apply -> 400
4) 用不存在的 ai_report_id -> 404
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.1 T4: apply_policy_suggestion type and status guards")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK")

    # 1) policy_suggest，不 tick，直接 apply -> 409
    r_ps = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None, "context_ref": "ref_t4"},
        timeout=timeout,
    )
    if r_ps.status_code != 202:
        print(f"FAIL: policy_suggest -> {r_ps.status_code} {r_ps.text}", file=sys.stderr)
        return 1
    ai_report_id = r_ps.json().get("ai_report_id")
    r_apply1 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": ai_report_id, "confirm": True},
        timeout=timeout,
    )
    if r_apply1.status_code != 409:
        print(f"FAIL: apply without tick expected 409, got {r_apply1.status_code} {r_apply1.text}", file=sys.stderr)
        return 1
    print("PASS: apply without tick -> 409")

    # 2) tick 后再 apply -> 202
    session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 2}, timeout=timeout)
    r_apply2 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": ai_report_id, "confirm": True},
        timeout=timeout,
    )
    if r_apply2.status_code != 202:
        print(f"FAIL: apply after tick expected 202, got {r_apply2.status_code} {r_apply2.text}", file=sys.stderr)
        return 1
    print("PASS: apply after tick -> 202")

    # 3) 用 DISPATCH_EXPLAIN 的 ai_report_id 去 apply -> 400（需先造一个 dispatch_explain job）
    r_res = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": "charger-002", "joykey": "joy_t4", "action": "HOLD"},
        timeout=timeout,
    )
    if r_res.status_code != 200:
        print(f"FAIL: reserve -> {r_res.status_code}", file=sys.stderr)
        return 1
    hold_id = r_res.json().get("hold_id")
    r_de = session.post(
        f"{base}/v1/ai/dispatch_explain",
        json={"hold_id": hold_id, "audience": "USER", "dispatch_reason_codes": ["CHARGER_BUSY"]},
        timeout=timeout,
    )
    if r_de.status_code != 202:
        print(f"FAIL: dispatch_explain -> {r_de.status_code} {r_de.text}", file=sys.stderr)
        return 1
    dispatch_report_id = r_de.json().get("ai_report_id")
    r_apply3 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": dispatch_report_id, "confirm": True},
        timeout=timeout,
    )
    if r_apply3.status_code != 400:
        print(f"FAIL: apply with dispatch report expected 400, got {r_apply3.status_code} {r_apply3.text}", file=sys.stderr)
        return 1
    print("PASS: apply with DISPATCH_EXPLAIN report_id -> 400")

    # 4) 不存在的 ai_report_id -> 404
    r_apply4 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": "airpt_nonexistent_999", "confirm": True},
        timeout=timeout,
    )
    if r_apply4.status_code != 404:
        print(f"FAIL: apply with nonexistent id expected 404, got {r_apply4.status_code} {r_apply4.text}", file=sys.stderr)
        return 1
    print("PASS: apply with nonexistent ai_report_id -> 404")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
