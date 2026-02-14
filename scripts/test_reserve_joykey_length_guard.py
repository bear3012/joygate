#!/usr/bin/env python3
"""reserve joykey 长度上限：<=128 正常；129 -> 400 invalid joykey。"""
from __future__ import annotations

import argparse
import sys

import requests


def _pick_free_charger(snapshot: dict) -> str | None:
    chargers = snapshot.get("chargers")
    if not isinstance(chargers, list):
        return None
    for c in chargers:
        if not isinstance(c, dict):
            continue
        if c.get("slot_state") == "FREE" and isinstance(c.get("charger_id"), str):
            return c["charger_id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Reserve joykey length guard: 200 on ok, 400 on too long")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    s = requests.Session()

    r_boot = s.get(f"{base}/bootstrap", timeout=args.timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: bootstrap {r_boot.status_code} body={r_boot.text}", file=sys.stderr)
        return 1
    if not s.cookies.get("joygate_sandbox"):
        print("FAIL: bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        return 1

    r_snap = s.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r_snap.status_code != 200:
        print(f"FAIL: snapshot {r_snap.status_code} body={r_snap.text}", file=sys.stderr)
        return 1
    snapshot = r_snap.json()
    charger_id = _pick_free_charger(snapshot)
    if not charger_id:
        print("FAIL: no FREE charger found in snapshot", file=sys.stderr)
        return 1

    url = f"{base}/v1/reserve"

    # Case 1: ok joykey -> 200
    payload_ok = {
        "resource_type": "charger",
        "resource_id": charger_id,
        "joykey": "jk_ok_len_guard",
        "action": "HOLD",
    }
    r1 = s.post(url, json=payload_ok, timeout=args.timeout)
    if r1.status_code != 200:
        print(f"FAIL: ok joykey -> expected 200, got {r1.status_code} body={r1.text}", file=sys.stderr)
        return 1
    print("OK: reserve with ok joykey -> 200")

    # Case 2: too long joykey -> 400 invalid joykey
    payload_bad = {
        "resource_type": "charger",
        "resource_id": charger_id,
        "joykey": "a" * 129,
        "action": "HOLD",
    }
    r2 = s.post(url, json=payload_bad, timeout=args.timeout)
    if r2.status_code != 400:
        print(f"FAIL: long joykey -> expected 400, got {r2.status_code} body={r2.text}", file=sys.stderr)
        return 1
    detail = ""
    try:
        if (r2.headers.get("content-type") or "").startswith("application/json"):
            detail = str(r2.json().get("detail", ""))
        else:
            detail = r2.text or ""
    except Exception:
        detail = r2.text or ""
    if "invalid joykey" not in detail:
        print(f"FAIL: long joykey -> detail must contain 'invalid joykey', got {detail!r}", file=sys.stderr)
        return 1
    print("OK: reserve with long joykey -> 400 (invalid joykey)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
