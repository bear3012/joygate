#!/usr/bin/env python3
"""
入口统一校验验收：所有进入 store 的字符串字段 strip、禁止前后空白、长度 64（evidence_refs 5 条/120）。
每类至少 2 个用例；错误 400 detail 形如 invalid <field_name>。
"""
from __future__ import annotations

import argparse
import sys

import requests

BASE_URL_DEFAULT = "http://127.0.0.1:8000"


def _detail(r: requests.Response) -> str:
    try:
        return (r.json() or {}).get("detail", "") or ""
    except Exception:
        return r.text or ""


def main() -> int:
    p = argparse.ArgumentParser(description="Entry input limits: 400 invalid <field> for overlong/whitespace")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT)
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # bootstrap
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}")
        return 1

    fails = 0

    # 1) charger_id 超长 65 → 400 invalid charger_id
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "x" * 65, "incident_type": "BLOCKED"},
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid charger_id" not in _detail(r):
        print(f"FAIL: charger_id 65 expected 400 invalid charger_id, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: charger_id 65 → 400 invalid charger_id")

    # 2) incident_type 前后空白 " BLOCKED " → 400 invalid incident_type
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "charger-001", "incident_type": " BLOCKED "},
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid incident_type" not in _detail(r):
        print(f"FAIL: incident_type whitespace expected 400 invalid incident_type, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: incident_type leading/trailing space → 400 invalid incident_type")

    # 3) snapshot_ref 超长（路由层 64）→ 400 invalid snapshot_ref
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "charger-001", "incident_type": "BLOCKED", "snapshot_ref": "s" * 65},
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid snapshot_ref" not in _detail(r):
        print(f"FAIL: snapshot_ref 65 (over 64) expected 400 invalid snapshot_ref, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: snapshot_ref 65 → 400 invalid snapshot_ref")

    # 4) points_event_id 超长 → 400 invalid points_event_id (segment_respond)
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={
            "segment_id": "cell_1_1",
            "segment_state": "PASSABLE",
            "points_event_id": "p" * 65,
        },
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid points_event_id" not in _detail(r):
        print(f"FAIL: points_event_id 65 expected 400 invalid points_event_id, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: points_event_id 65 → 400 invalid points_event_id")

    # 5) segment_id 超长 (telemetry)
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "jk1",
            "segment_ids": ["cell_1_1", "x" * 65],
            "event_occurred_at": 1e9,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid segment_ids" not in _detail(r):
        print(f"FAIL: segment_ids one overlong expected 400 invalid segment_ids, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: segment_ids overlong → 400 invalid segment_ids")

    # 6) event_occurred_at 传超长字符串 → 400 invalid event_occurred_at (work_orders)
    r = session.post(
        f"{base}/v1/work_orders/report",
        json={
            "work_order_id": "wo_123",
            "work_order_status": "OPEN",
            "event_occurred_at": "t" * 65,
        },
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid event_occurred_at" not in _detail(r):
        print(f"FAIL: event_occurred_at str 65 expected 400 invalid event_occurred_at, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: event_occurred_at str 65 → 400 invalid event_occurred_at")

    # 7) evidence_refs 超长元素 → 400 invalid evidence_refs
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "evidence_refs": ["ok", "e" * 121],
        },
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid evidence_refs" not in _detail(r):
        print(f"FAIL: evidence_refs overlong element expected 400 invalid evidence_refs, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: evidence_refs overlong element → 400 invalid evidence_refs")

    # 8) evidence_refs 带前后空白元素 → 400 invalid evidence_refs
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "evidence_refs": ["  ev1  "],
        },
        timeout=timeout,
    )
    if r.status_code != 400 or "invalid evidence_refs" not in _detail(r):
        print(f"FAIL: evidence_refs whitespace expected 400 invalid evidence_refs, got {r.status_code} detail={_detail(r)}")
        fails += 1
    else:
        print("OK: evidence_refs element with spaces → 400 invalid evidence_refs")

    if fails:
        print(f"FAIL: {fails} case(s) failed")
        return 1
    print("PASS: all entry input limit checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
