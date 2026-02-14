#!/usr/bin/env python3
"""
Proactive congestion：同一 charger_id 在 120s 窗口内 ≥3 个不同 joykey 的 reserve 409
→ ledger 出现去重的一条 POLICY_SUGGESTED，summary 含 proactive_congestion、delay_charging_seconds=120。
流程：bootstrap → reserve charger-001 用 proactive_owner(200) → p1/p2/p3 各 reserve charger-001(409)
→ GET audit/ledger → 断言 decisions 中含 POLICY_SUGGESTED 且 summary 含 proactive_congestion、charger_id=charger-001、delay_charging_seconds=120。
"""
from __future__ import annotations

import argparse
import sys

import requests

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
CHARGER_ID = "charger-001"


def main() -> int:
    parser = argparse.ArgumentParser(description="Proactive delay_charging suggestion: 3x 409 -> ledger POLICY_SUGGESTED")
    parser.add_argument("--base_url", default=BASE_URL_DEFAULT)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # bootstrap（复用 test_m11 方式）
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}", file=sys.stderr)
        return 1
    if not session.cookies.get("joygate_sandbox"):
        print("FAIL: bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        return 1
    print("bootstrap OK, cookie set")

    # reserve charger-001 用 proactive_owner -> 200
    r = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": CHARGER_ID, "joykey": "proactive_owner", "action": "HOLD"},
        timeout=timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: reserve proactive_owner -> {r.status_code} {r.text}", file=sys.stderr)
        return 1
    print("reserve proactive_owner -> 200 hold")

    # 3 个不同 joykey 各自对 charger-001 reserve -> 409
    for joykey in ("p1", "p2", "p3"):
        r = session.post(
            f"{base}/v1/reserve",
            json={"resource_type": "charger", "resource_id": CHARGER_ID, "joykey": joykey, "action": "HOLD"},
            timeout=timeout,
        )
        if r.status_code != 409:
            print(f"FAIL: reserve {joykey} expected 409, got {r.status_code} {r.text}", file=sys.stderr)
            return 1
        print(f"reserve {joykey} -> 409")

    # GET audit/ledger
    r = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET ledger {r.status_code}", file=sys.stderr)
        return 1
    try:
        data = r.json()
    except Exception:
        print("FAIL: ledger response not JSON", file=sys.stderr)
        return 1
    decisions = data.get("decisions") or []
    if not isinstance(decisions, list):
        print("FAIL: decisions not a list", file=sys.stderr)
        return 1

    # 找 decision_type == POLICY_SUGGESTED，summary 含 proactive_congestion、charger_id=charger-001、delay_charging_seconds=120
    found = False
    for d in decisions:
        if not isinstance(d, dict):
            continue
        if d.get("decision_type") != "POLICY_SUGGESTED":
            continue
        summary = (d.get("summary") or "")
        if "proactive congestion" not in summary:
            continue
        if f"charger_id={CHARGER_ID}" not in summary:
            continue
        if "delay_charging_seconds=120" not in summary:
            continue
        found = True
        print(f"found POLICY_SUGGESTED: summary={summary[:120]}...")
        break

    if not found:
        print("FAIL: no decision with decision_type=POLICY_SUGGESTED and summary containing proactive_congestion, charger_id=charger-001, delay_charging_seconds=120", file=sys.stderr)
        print(f"decisions sample: {[dict(d) for d in decisions[-5:]]}", file=sys.stderr)
        return 1
    print("PASS: proactive delay_charging suggestion in ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
