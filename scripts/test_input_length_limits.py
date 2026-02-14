#!/usr/bin/env python3
"""输入长度上限：joykey<=128、incident_id<=64、snapshot_ref<=256，超长 400。"""
from __future__ import annotations

import argparse
import sys
import time

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Input length limits: joykey/snapshot_ref/incident_id caps")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=args.timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: bootstrap {r_boot.status_code}", file=sys.stderr)
        return 1
    if not session.cookies.get("joygate_sandbox"):
        print("FAIL: bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        return 1

    # Case A: joykey 129 字符 -> 400 invalid joykey
    payload_a = {
        "joykey": "j" * 129,
        "segment_ids": ["cell_0_0"],
        "truth_input_source": "SIMULATOR",
        "event_occurred_at": time.time(),
    }
    r_a = session.post(f"{base}/v1/telemetry/segment_passed", json=payload_a, timeout=args.timeout)
    if r_a.status_code != 400:
        print(f"FAIL: Case A expected 400, got {r_a.status_code} body={r_a.text}", file=sys.stderr)
        return 1
    detail_a = r_a.json().get("detail", "") if r_a.headers.get("content-type", "").startswith("application/json") else r_a.text
    if "invalid joykey" not in str(detail_a):
        print(f"FAIL: Case A detail must contain 'invalid joykey', got {detail_a}", file=sys.stderr)
        return 1
    print("OK: Case A joykey 129 -> 400 invalid joykey")

    # Case B: snapshot_ref 257 字符 -> 400 invalid snapshot_ref
    payload_b = {
        "charger_id": "charger-001",
        "incident_type": "BLOCKED",
        "snapshot_ref": "s" * 257,
    }
    r_b = session.post(f"{base}/v1/incidents/report_blocked", json=payload_b, timeout=args.timeout)
    if r_b.status_code != 400:
        print(f"FAIL: Case B expected 400, got {r_b.status_code} body={r_b.text}", file=sys.stderr)
        return 1
    detail_b = r_b.json().get("detail", "") if r_b.headers.get("content-type", "").startswith("application/json") else r_b.text
    if "invalid snapshot_ref" not in str(detail_b):
        print(f"FAIL: Case B detail must contain 'invalid snapshot_ref', got {detail_b}", file=sys.stderr)
        return 1
    print("OK: Case B snapshot_ref 257 -> 400 invalid snapshot_ref")

    # Case C: incident_id 65 字符 -> 400 invalid incident_id
    payload_c = {
        "incident_id": "i" * 65,
        "incident_status": "OPEN",
    }
    r_c = session.post(f"{base}/v1/incidents/update_status", json=payload_c, timeout=args.timeout)
    if r_c.status_code != 400:
        print(f"FAIL: Case C expected 400, got {r_c.status_code} body={r_c.text}", file=sys.stderr)
        return 1
    detail_c = r_c.json().get("detail", "") if r_c.headers.get("content-type", "").startswith("application/json") else r_c.text
    if "invalid incident_id" not in str(detail_c):
        print(f"FAIL: Case C detail must contain 'invalid incident_id', got {detail_c}", file=sys.stderr)
        return 1
    print("OK: Case C incident_id 65 -> 400 invalid incident_id")
    return 0


if __name__ == "__main__":
    sys.exit(main())
