#!/usr/bin/env python3
"""reserve 输入守卫：resource_type/resource_id/joykey/action strip+非空+长度；超长或空白 400。"""
from __future__ import annotations

import argparse
import sys

import requests


def _detail(r) -> str:
    if (r.headers.get("content-type") or "").startswith("application/json"):
        return str(r.json().get("detail", ""))
    return r.text or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Reserve input length guard: normal 200, too long/whitespace 400")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=args.timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: bootstrap {r_boot.status_code} body={r_boot.text}", file=sys.stderr)
        return 1
    if not session.cookies.get("joygate_sandbox"):
        print("FAIL: bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        return 1

    url = f"{base}/v1/reserve"

    # Case 1: normal -> 200
    r1 = session.post(
        url,
        json={
            "resource_type": "charger",
            "resource_id": "charger-001",
            "joykey": "jk_ok",
            "action": "HOLD",
        },
        timeout=args.timeout,
    )
    if r1.status_code != 200:
        print(f"FAIL: reserve normal -> expected 200, got {r1.status_code} body={r1.text}", file=sys.stderr)
        return 1
    print("OK: reserve normal -> 200")

    # Case 2: joykey 129 -> 400 invalid joykey
    r2 = session.post(
        url,
        json={
            "resource_type": "charger",
            "resource_id": "charger-002",
            "joykey": "j" * 129,
            "action": "HOLD",
        },
        timeout=args.timeout,
    )
    if r2.status_code != 400 or "invalid joykey" not in _detail(r2):
        print(f"FAIL: joykey too long -> expected 400 invalid joykey, got {r2.status_code} detail={_detail(r2)}", file=sys.stderr)
        return 1
    print("OK: joykey too long -> 400 (invalid joykey)")

    # Case 3: resource_id 1000 -> 400 invalid resource_id
    r3 = session.post(
        url,
        json={
            "resource_type": "charger",
            "resource_id": "c" * 1000,
            "joykey": "jk_guard",
            "action": "HOLD",
        },
        timeout=args.timeout,
    )
    if r3.status_code != 400 or "invalid resource_id" not in _detail(r3):
        print(f"FAIL: resource_id too long -> expected 400 invalid resource_id, got {r3.status_code} detail={_detail(r3)}", file=sys.stderr)
        return 1
    print("OK: resource_id too long -> 400 (invalid resource_id)")

    # Case 4: resource_type 1000 -> 400 invalid resource_type
    r4 = session.post(
        url,
        json={
            "resource_type": "t" * 1000,
            "resource_id": "charger-003",
            "joykey": "jk_guard",
            "action": "HOLD",
        },
        timeout=args.timeout,
    )
    if r4.status_code != 400 or "invalid resource_type" not in _detail(r4):
        print(f"FAIL: resource_type too long -> expected 400 invalid resource_type, got {r4.status_code} detail={_detail(r4)}", file=sys.stderr)
        return 1
    print("OK: resource_type too long -> 400 (invalid resource_type)")

    # Case 5: action "HOLD " (trailing space) -> 400 invalid action
    r5 = session.post(
        url,
        json={
            "resource_type": "charger",
            "resource_id": "charger-004",
            "joykey": "jk_guard",
            "action": "HOLD ",
        },
        timeout=args.timeout,
    )
    if r5.status_code != 400 or "invalid action" not in _detail(r5):
        print(f"FAIL: action has whitespace -> expected 400 invalid action, got {r5.status_code} detail={_detail(r5)}", file=sys.stderr)
        return 1
    print("OK: action has whitespace -> 400 (invalid action)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
