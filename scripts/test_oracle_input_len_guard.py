#!/usr/bin/env python3
"""oracle start_charging/stop_charging 输入长度守卫：hold_id/charger_id/meter_session_id/event_occurred_at 超长 400。"""
from __future__ import annotations

import argparse
import sys

import requests


def _detail(r) -> str:
    if (r.headers.get("content-type") or "").startswith("application/json"):
        return str(r.json().get("detail", ""))
    return r.text or ""


def _pick_free_charger(snapshot: dict) -> str | None:
    for c in snapshot.get("chargers") or []:
        if isinstance(c, dict) and c.get("slot_state") == "FREE" and isinstance(c.get("charger_id"), str):
            return c["charger_id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Oracle input length guard: hold_id/charger_id/meter_session_id/event_occurred_at")
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

    r_snap = session.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r_snap.status_code != 200:
        print(f"FAIL: snapshot {r_snap.status_code}", file=sys.stderr)
        return 1
    charger_id = _pick_free_charger(r_snap.json())
    if not charger_id:
        print("FAIL: no FREE charger in snapshot", file=sys.stderr)
        return 1

    r_reserve = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": charger_id, "joykey": "jk_oracle_guard", "action": "HOLD"},
        timeout=args.timeout,
    )
    if r_reserve.status_code != 200:
        print(f"FAIL: reserve {r_reserve.status_code} body={r_reserve.text}", file=sys.stderr)
        return 1
    hold_id = r_reserve.json().get("hold_id")
    if not hold_id:
        print("FAIL: reserve did not return hold_id", file=sys.stderr)
        return 1

    url_start = f"{base}/v1/oracle/start_charging"
    base_payload = {
        "hold_id": hold_id,
        "charger_id": charger_id,
        "meter_session_id": "ms_001",
        "event_occurred_at": "2025-01-01T00:00:00Z",
    }

    # Case 1: normal -> 200
    r1 = session.post(url_start, json=base_payload, timeout=args.timeout)
    if r1.status_code != 200:
        print(f"FAIL: oracle_start normal -> expected 200, got {r1.status_code} body={r1.text}", file=sys.stderr)
        return 1
    print("OK: oracle_start normal -> 200")

    # Case 2: hold_id too long -> 400
    p2 = {**base_payload, "hold_id": "h" * 2000}
    r2 = session.post(url_start, json=p2, timeout=args.timeout)
    if r2.status_code != 400 or "invalid hold_id" not in _detail(r2):
        print(f"FAIL: hold_id too long -> expected 400 invalid hold_id, got {r2.status_code} detail={_detail(r2)}", file=sys.stderr)
        return 1
    print("OK: hold_id too long -> 400 (invalid hold_id)")

    # Case 3: charger_id too long -> 400
    p3 = {**base_payload, "charger_id": "c" * 2000}
    r3 = session.post(url_start, json=p3, timeout=args.timeout)
    if r3.status_code != 400 or "invalid charger_id" not in _detail(r3):
        print(f"FAIL: charger_id too long -> expected 400 invalid charger_id, got {r3.status_code} detail={_detail(r3)}", file=sys.stderr)
        return 1
    print("OK: charger_id too long -> 400 (invalid charger_id)")

    # Case 4: meter_session_id too long -> 400
    p4 = {**base_payload, "meter_session_id": "m" * 2000}
    r4 = session.post(url_start, json=p4, timeout=args.timeout)
    if r4.status_code != 400 or "invalid meter_session_id" not in _detail(r4):
        print(f"FAIL: meter_session_id too long -> expected 400 invalid meter_session_id, got {r4.status_code} detail={_detail(r4)}", file=sys.stderr)
        return 1
    print("OK: meter_session_id too long -> 400 (invalid meter_session_id)")

    # Case 5: event_occurred_at too long -> 400
    p5 = {**base_payload, "event_occurred_at": "t" * 2000}
    r5 = session.post(url_start, json=p5, timeout=args.timeout)
    if r5.status_code != 400 or "invalid event_occurred_at" not in _detail(r5):
        print(f"FAIL: event_occurred_at too long -> expected 400 invalid event_occurred_at, got {r5.status_code} detail={_detail(r5)}", file=sys.stderr)
        return 1
    print("OK: event_occurred_at too long -> 400 (invalid event_occurred_at)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
