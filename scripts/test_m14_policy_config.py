#!/usr/bin/env python3
"""M14.1 验收：GET /v1/policy 返回 store.get_policy()，断言 200 及 POLICY_CONFIG 关键 key 存在。"""
from __future__ import annotations

import argparse
import json
import sys

import requests

REQUIRED_POLICY_KEYS = [
    "soft_hazard_recheck_interval_minutes",
    "soft_hazard_escalate_after_rechecks",
    "segment_witness_votes_required",
    "segment_witness_sla_timeout_minutes",
    "segment_freshness_window_minutes",
    "vision_audit_budget_global",
    "vision_audit_budget_per_vendor",
    "witness_votes_required",
    "witness_sla_timeout_minutes",
]


def main() -> int:
    p = argparse.ArgumentParser(description="M14.1 policy config acceptance")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    url = f"{base}/v1/policy"

    r = requests.get(url, timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL: GET /v1/policy status={r.status_code} body={r.text}", file=sys.stderr)
        return 1

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        print(f"FAIL: response not JSON: {e} body={r.text}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print(f"FAIL: response not a dict: {type(data)}", file=sys.stderr)
        return 1

    missing = [k for k in REQUIRED_POLICY_KEYS if k not in data]
    if missing:
        print(f"FAIL: missing keys: {missing}", file=sys.stderr)
        return 1

    print("PASS policy keys OK")
    print(json.dumps(data, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise
