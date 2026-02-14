#!/usr/bin/env python3
"""incident_id / snapshot_ref 长度守卫：GET 与 POST 超长 400，边界 256 通过。"""
from __future__ import annotations

import argparse
import sys

import requests


def _detail(r) -> str:
    if r.headers.get("content-type", "").startswith("application/json"):
        return str(r.json().get("detail", ""))
    return r.text or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Incident input length guards: incident_id 64, snapshot_ref 256")
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

    # 1) GET /v1/incidents?incident_id= 65 chars -> 400, detail=invalid incident_id
    r1 = session.get(f"{base}/v1/incidents", params={"incident_id": "i" * 65}, timeout=args.timeout)
    if r1.status_code != 400:
        print(f"FAIL: GET incident_id=65chars expected 400, got {r1.status_code} body={r1.text}", file=sys.stderr)
        return 1
    if "invalid incident_id" not in _detail(r1):
        print(f"FAIL: GET incident_id=65chars detail must contain 'invalid incident_id', got {_detail(r1)}", file=sys.stderr)
        return 1
    print("OK: GET /v1/incidents?incident_id=65chars -> 400 invalid incident_id")

    # 2) POST /v1/incidents/update_status body incident_id 65 chars -> 400, detail=invalid incident_id
    r2 = session.post(
        f"{base}/v1/incidents/update_status",
        json={"incident_id": "i" * 65, "incident_status": "OPEN"},
        timeout=args.timeout,
    )
    if r2.status_code != 400:
        print(f"FAIL: POST update_status incident_id=65chars expected 400, got {r2.status_code} body={r2.text}", file=sys.stderr)
        return 1
    if "invalid incident_id" not in _detail(r2):
        print(f"FAIL: POST update_status detail must contain 'invalid incident_id', got {_detail(r2)}", file=sys.stderr)
        return 1
    print("OK: POST update_status incident_id=65chars -> 400 invalid incident_id")

    # 3) POST /v1/incidents/report_blocked snapshot_ref 256 -> 200
    r3 = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "s" * 256,
        },
        timeout=args.timeout,
    )
    if r3.status_code != 200:
        print(f"FAIL: report_blocked snapshot_ref=256 expected 200, got {r3.status_code} body={r3.text}", file=sys.stderr)
        return 1
    print("OK: POST report_blocked snapshot_ref=256 -> 200")

    # 4) POST /v1/incidents/report_blocked snapshot_ref 257 -> 400, detail=invalid snapshot_ref
    r4 = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={
            "charger_id": "charger-002",
            "incident_type": "BLOCKED",
            "snapshot_ref": "s" * 257,
        },
        timeout=args.timeout,
    )
    if r4.status_code != 400:
        print(f"FAIL: report_blocked snapshot_ref=257 expected 400, got {r4.status_code} body={r4.text}", file=sys.stderr)
        return 1
    if "invalid snapshot_ref" not in _detail(r4):
        print(f"FAIL: report_blocked snapshot_ref=257 detail must contain 'invalid snapshot_ref', got {_detail(r4)}", file=sys.stderr)
        return 1
    print("OK: POST report_blocked snapshot_ref=257 -> 400 invalid snapshot_ref")
    return 0


if __name__ == "__main__":
    sys.exit(main())
