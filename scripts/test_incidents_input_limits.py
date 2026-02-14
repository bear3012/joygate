#!/usr/bin/env python3
"""Incidents 输入限长/空白守卫：charger_id/incident_type/snapshot_ref."""
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


def _must_400(r: requests.Response, contains: str) -> None:
    if r.status_code != 400 or contains not in _detail(r):
        raise RuntimeError(f"expected 400 contains={contains!r}, got {r.status_code} detail={_detail(r)!r}")


def _must_200_json_has_incident_id(r: requests.Response) -> None:
    if r.status_code != 200:
        raise RuntimeError(f"expected 200, got {r.status_code} body={r.text}")
    obj = r.json()
    if not isinstance(obj.get("incident_id"), str) or not obj["incident_id"]:
        raise RuntimeError(f"missing incident_id body={r.text}")


def main() -> int:
    p = argparse.ArgumentParser(description="Incidents input limits test")
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

    # A) charger_id whitespace -> 400 invalid charger_id
    r = s.post(
        url,
        json={
            "charger_id": " charger-001 ",
            "incident_type": "BLOCKED",
            "snapshot_ref": f"sr_{int(time.time())}",
        },
        timeout=args.timeout,
    )
    _must_400(r, "invalid charger_id")
    print("OK: charger_id whitespace -> 400 invalid charger_id")

    # B) charger_id too long (65) -> 400 invalid charger_id
    r = s.post(
        url,
        json={
            "charger_id": "x" * 65,
            "incident_type": "BLOCKED",
            "snapshot_ref": f"sr_{int(time.time())}",
        },
        timeout=args.timeout,
    )
    _must_400(r, "invalid charger_id")
    print("OK: charger_id too long -> 400 invalid charger_id")

    # C) incident_type whitespace -> 400 invalid incident_type
    r = s.post(
        url,
        json={
            "charger_id": "charger-001",
            "incident_type": " BLOCKED",
            "snapshot_ref": f"sr_{int(time.time())}",
        },
        timeout=args.timeout,
    )
    _must_400(r, "invalid incident_type")
    print("OK: incident_type whitespace -> 400 invalid incident_type")

    # D) snapshot_ref too long (257) -> 400 invalid snapshot_ref
    r = s.post(
        url,
        json={
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "s" * 257,
        },
        timeout=args.timeout,
    )
    _must_400(r, "invalid snapshot_ref")
    print("OK: snapshot_ref too long -> 400 invalid snapshot_ref")

    # E) valid -> 200, has incident_id
    r = s.post(
        url,
        json={
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": f"sr_{int(time.time())}",
            "evidence_refs": ["ev_ok_1"],
        },
        timeout=args.timeout,
    )
    _must_200_json_has_incident_id(r)
    print("OK: valid report_blocked -> 200")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FAIL: {e!s}", file=sys.stderr)
        raise
