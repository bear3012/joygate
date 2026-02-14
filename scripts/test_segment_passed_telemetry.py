#!/usr/bin/env python3
"""
M10 POST /v1/telemetry/segment_passed 验收：
bootstrap cookie -> (A) 正常 204 (B) snapshot 含 cell_1_1/cell_1_2 (C) 更早时间不回退 (D) 未来时间 400
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts_dir))
from _sandbox_client import get_bootstrapped_session  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="M10 segment_passed telemetry test")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")

    session = get_bootstrapped_session(base, args.timeout)

    now = time.time()

    # A) 正常：event_occurred_at = now-2, segment_ids = ["cell_1_1","cell_1_2"] -> 204
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "jk_m10_test",
            "fleet_id": None,
            "segment_ids": ["cell_1_1", "cell_1_2"],
            "event_occurred_at": now - 2,
            "truth_input_source": "SIMULATOR",
        },
        timeout=args.timeout,
    )
    if r.status_code != 204:
        print(f"FAIL A: POST segment_passed -> {r.status_code} (expected 204)")
        print(r.text)
        return 1
    print("A) POST /v1/telemetry/segment_passed (now-2, cell_1_1, cell_1_2) -> 204")

    # B) GET snapshot，断言能看到 cell_1_1 / cell_1_2 的 last_passed_at
    r = session.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL B: GET snapshot -> {r.status_code}")
        return 1
    data = r.json()
    signals = data.get("segment_passed_signals") or []
    by_seg = {s["segment_id"]: s for s in signals if isinstance(s, dict)}
    if "cell_1_1" not in by_seg or "cell_1_2" not in by_seg:
        print("FAIL B: snapshot segment_passed_signals missing cell_1_1 or cell_1_2")
        print("signals:", signals)
        return 1
    t1 = by_seg["cell_1_1"].get("last_passed_at")
    t2 = by_seg["cell_1_2"].get("last_passed_at")
    print(f"B) GET /v1/snapshot -> segment_passed_signals: cell_1_1 last_passed_at={t1}, cell_1_2 last_passed_at={t2}")

    # C) 再 POST cell_1_1 用更早 event_occurred_at = now-100 -> 204，再 GET snapshot，断言 last_passed_at 不回退
    before = t1
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "jk_m10_test",
            "fleet_id": None,
            "segment_ids": ["cell_1_1"],
            "event_occurred_at": now - 100,
            "truth_input_source": "SIMULATOR",
        },
        timeout=args.timeout,
    )
    if r.status_code != 204:
        print(f"FAIL C: POST segment_passed (older) -> {r.status_code}")
        return 1
    r = session.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL C: GET snapshot -> {r.status_code}")
        return 1
    signals = r.json().get("segment_passed_signals") or []
    by_seg = {s["segment_id"]: s for s in signals if isinstance(s, dict)}
    after = by_seg.get("cell_1_1", {}).get("last_passed_at")
    if after != before:
        print(f"FAIL C: last_passed_at should not go back: before={before} after={after}")
        return 1
    print(f"C) POST cell_1_1 (now-100) -> 204; GET snapshot: last_passed_at unchanged before={before} after={after}")

    # D) POST 明显未来 event_occurred_at = now+3600 -> 400
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "jk_m10_test",
            "fleet_id": None,
            "segment_ids": ["cell_9_9"],
            "event_occurred_at": now + 3600,
            "truth_input_source": "SIMULATOR",
        },
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL D: POST segment_passed (future) -> {r.status_code} (expected 400)")
        print(r.text)
        return 1
    print(f"D) POST segment_passed (now+3600) -> 400 body: {r.text}")

    print("OK: M10 segment_passed telemetry passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
