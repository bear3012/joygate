#!/usr/bin/env python3
"""
Segment witness 证据入口 points_event_id 必填验收：
负例：缺 points_event_id -> 400 invalid points_event_id；points_event_id 空白/前后空白 -> 400
正例：合法 points_event_id -> 204
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts_dir))
from _sandbox_client import get_bootstrapped_session  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="segment_respond points_event_id required")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    session = get_bootstrapped_session(base, args.timeout)
    headers = {"X-JoyKey": "w1"}

    # 负例 1：缺 points_event_id -> 400，detail 含 invalid points_event_id
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={"segment_id": "cell_0_0", "hazard_status": "BLOCKED"},
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: missing points_event_id -> expected 400, got {r.status_code}")
        print(r.text)
        return 1
    try:
        j = r.json()
        detail = j.get("detail")
    except Exception:
        detail = r.text
    if "invalid points_event_id" not in str(detail):
        print(f"FAIL: expected detail containing 'invalid points_event_id', got: {detail}")
        return 1
    print("OK: missing points_event_id -> 400 invalid points_event_id")

    # 负例 2：points_event_id 仅空白 -> 400
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={"segment_id": "cell_0_1", "hazard_status": "BLOCKED", "points_event_id": "   "},
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: points_event_id whitespace -> expected 400, got {r.status_code}")
        print(r.text)
        return 1
    try:
        j = r.json()
        detail = j.get("detail")
    except Exception:
        detail = r.text
    if "invalid points_event_id" not in str(detail):
        print(f"FAIL: expected detail containing 'invalid points_event_id', got: {detail}")
        return 1
    print("OK: points_event_id whitespace -> 400 invalid points_event_id")

    # 负例 3：points_event_id 前后带空白 -> 400
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={"segment_id": "cell_0_2", "hazard_status": "BLOCKED", "points_event_id": "  pe_ok  "},
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: points_event_id leading/trailing space -> expected 400, got {r.status_code}")
        print(r.text)
        return 1
    try:
        j = r.json()
        detail = j.get("detail")
    except Exception:
        detail = r.text
    if "invalid points_event_id" not in str(detail):
        print(f"FAIL: expected detail containing 'invalid points_event_id', got: {detail}")
        return 1
    print("OK: points_event_id leading/trailing space -> 400 invalid points_event_id")

    # 正例：合法 points_event_id -> 204
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={"segment_id": "cell_1_1", "hazard_status": "BLOCKED", "points_event_id": "pe_positive_01"},
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: valid points_event_id -> expected 204, got {r.status_code}")
        print(r.text)
        return 1
    print("OK: valid points_event_id -> 204")
    return 0


if __name__ == "__main__":
    sys.exit(main())
