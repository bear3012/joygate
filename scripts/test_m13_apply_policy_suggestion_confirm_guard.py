#!/usr/bin/env python3
"""
M13.1 T2：apply_policy_suggestion confirm 护栏。
confirm=false -> 400 PASS；confirm=true -> 202 PASS + ledger 有 POLICY_APPLIED。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.1 T2: apply_policy_suggestion confirm guard + POLICY_APPLIED")
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

    r_400 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": "airpt_dummy_t2", "confirm": False},
        timeout=timeout,
    )
    if r_400.status_code != 400:
        print(f"FAIL: confirm=false expected 400, got {r_400.status_code} {r_400.text}", file=sys.stderr)
        return 1
    print("PASS: confirm=false -> 400")

    # 造一个已完成的 policy_suggest，再 apply
    r_ps = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None, "context_ref": "ref_t2"},
        timeout=timeout,
    )
    if r_ps.status_code != 202:
        print(f"FAIL: policy_suggest -> {r_ps.status_code} {r_ps.text}", file=sys.stderr)
        return 1
    ai_report_id = r_ps.json().get("ai_report_id")
    session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 2}, timeout=timeout)
    r_202 = session.post(
        f"{base}/v1/admin/apply_policy_suggestion",
        json={"ai_report_id": ai_report_id, "confirm": True},
        timeout=timeout,
    )
    if r_202.status_code != 202:
        print(f"FAIL: confirm=true expected 202, got {r_202.status_code} {r_202.text}", file=sys.stderr)
        return 1
    print("PASS: confirm=true -> 202")

    r_ledger = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger.status_code != 200:
        print(f"FAIL: GET ledger -> {r_ledger.status_code}", file=sys.stderr)
        return 1
    decisions = r_ledger.json().get("decisions") or []
    applied = [d for d in decisions if d.get("decision_type") == "POLICY_APPLIED"]
    if not applied:
        print("FAIL: ledger has no POLICY_APPLIED after confirm=true", file=sys.stderr)
        return 1
    print("PASS: ledger has POLICY_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
