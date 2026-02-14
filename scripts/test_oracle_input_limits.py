#!/usr/bin/env python3
"""Oracle 输入长度上限：超长/空白 -> 400；合法 -> 200。"""
from __future__ import annotations

import argparse
import sys
import time

import requests


def _must_400(r: requests.Response, msg: str) -> None:
    if r.status_code != 400:
        raise AssertionError(f"{msg}: expected 400, got {r.status_code} body={r.text}")
    print(f"OK: {msg} -> 400")


def _must_200(r: requests.Response, msg: str) -> None:
    if r.status_code != 200:
        raise AssertionError(f"{msg}: expected 200, got {r.status_code} body={r.text}")
    print(f"OK: {msg} -> 200")


def main() -> int:
    p = argparse.ArgumentParser(description="Oracle input limits test")
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

    # reserve -> get a real hold_id for positive case
    r = s.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": "charger-001", "joykey": "jk_oracle_len", "action": "HOLD"},
        timeout=args.timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: reserve {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    hold_id = r.json().get("hold_id")
    if not isinstance(hold_id, str) or not hold_id:
        print(f"FAIL: reserve missing hold_id body={r.text}", file=sys.stderr)
        return 1

    url_start = f"{base}/v1/oracle/start_charging"
    url_stop = f"{base}/v1/oracle/stop_charging"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Case A: hold_id 超长
    r = s.post(
        url_start,
        json={"hold_id": "x" * 65, "charger_id": "charger-001", "meter_session_id": "ms_1", "event_occurred_at": now_iso},
        timeout=args.timeout,
    )
    _must_400(r, "start_charging invalid hold_id (too long)")

    # Case B: meter_session_id 超长
    r = s.post(
        url_start,
        json={"hold_id": hold_id, "charger_id": "charger-001", "meter_session_id": "m" * 65, "event_occurred_at": now_iso},
        timeout=args.timeout,
    )
    _must_400(r, "start_charging invalid meter_session_id (too long)")

    # Case C: charger_id 带空白
    r = s.post(
        url_start,
        json={"hold_id": hold_id, "charger_id": " charger-001 ", "meter_session_id": "ms_1", "event_occurred_at": now_iso},
        timeout=args.timeout,
    )
    _must_400(r, "start_charging invalid charger_id (whitespace)")

    # Case D: 合法 start
    r = s.post(
        url_start,
        json={"hold_id": hold_id, "charger_id": "charger-001", "meter_session_id": "ms_1", "event_occurred_at": now_iso},
        timeout=args.timeout,
    )
    _must_200(r, "start_charging valid")

    # Case E: event_occurred_at 超长
    r = s.post(
        url_stop,
        json={"hold_id": hold_id, "charger_id": "charger-001", "meter_session_id": "ms_1", "event_occurred_at": "t" * 65},
        timeout=args.timeout,
    )
    _must_400(r, "stop_charging invalid event_occurred_at (too long)")

    # Case F: 合法 stop
    r = s.post(
        url_stop,
        json={"hold_id": hold_id, "charger_id": "charger-001", "meter_session_id": "ms_1", "event_occurred_at": now_iso},
        timeout=args.timeout,
    )
    _must_200(r, "stop_charging valid")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise
