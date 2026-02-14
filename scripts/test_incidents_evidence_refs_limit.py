#!/usr/bin/env python3
"""incidents/report_blocked evidence_refs 上限：21条->400 too many evidence_refs；单条过长->400 invalid evidence_ref；合法->200."""
from __future__ import annotations

import argparse
import sys
import time

import requests


def _detail(r: requests.Response) -> str:
    try:
        return (r.json() or {}).get("detail", "") or ""
    except Exception:
        return r.text or ""


def main() -> int:
    p = argparse.ArgumentParser(description="evidence_refs limit test")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    s = requests.Session()

    # bootstrap -> cookie
    r = s.get(f"{base}/bootstrap", timeout=args.timeout)
    if r.status_code != 200 or not s.cookies.get("joygate_sandbox"):
        print(f"FAIL: bootstrap {r.status_code} cookie={s.cookies.get('joygate_sandbox')!r} body={r.text}", file=sys.stderr)
        return 1

    url = f"{base}/v1/incidents/report_blocked"

    # Case A: 21 refs -> 400 too many evidence_refs
    payload = {
        "charger_id": "charger-001",
        "incident_type": "BLOCKED",
        "snapshot_ref": f"sr_{int(time.time())}",
        "evidence_refs": [f"ev_{i}" for i in range(21)],
    }
    r = s.post(url, json=payload, timeout=args.timeout)
    detail_a = _detail(r)
    if r.status_code != 400 or "too many evidence_refs" not in detail_a:
        print(f"FAIL: Case A expected 400 too many evidence_refs, got {r.status_code} detail={detail_a!r}", file=sys.stderr)
        return 1
    print("OK: 21 evidence_refs -> 400 (too many evidence_refs)")

    # Case B: single ref too long -> 400 invalid evidence_ref
    payload = {
        "charger_id": "charger-001",
        "incident_type": "BLOCKED",
        "snapshot_ref": f"sr_{int(time.time())}",
        "evidence_refs": ["x" * 257],
    }
    r = s.post(url, json=payload, timeout=args.timeout)
    detail_b = _detail(r)
    if r.status_code != 400 or "invalid evidence_ref" not in detail_b:
        print(f"FAIL: Case B expected 400 invalid evidence_ref, got {r.status_code} detail={detail_b!r}", file=sys.stderr)
        return 1
    print("OK: long evidence_ref -> 400 (invalid evidence_ref)")

    # Case C: valid 2 refs -> 200, body has incident_id
    payload = {
        "charger_id": "charger-001",
        "incident_type": "BLOCKED",
        "snapshot_ref": f"sr_{int(time.time())}",
        "evidence_refs": ["ev_ok_1", "ev_ok_2"],
    }
    r = s.post(url, json=payload, timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL: Case C expected 200, got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    try:
        obj = r.json()
    except Exception:
        print(f"FAIL: Case C expected JSON, got body={r.text}", file=sys.stderr)
        return 1
    if not isinstance(obj.get("incident_id"), str) or not obj["incident_id"]:
        print(f"FAIL: Case C missing incident_id body={r.text}", file=sys.stderr)
        return 1
    print("OK: valid evidence_refs -> 200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
