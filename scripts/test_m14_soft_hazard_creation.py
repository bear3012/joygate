#!/usr/bin/env python3
"""
M14.4 验收：BLOCKED 制度化 SOFT hazard；PASSABLE 不创建 OPEN。
bootstrap -> POST BLOCKED cell_12_34 -> GET snapshot 断言 SOFT_BLOCKED/SOFT_RECHECK/recheck_due_at
-> POST PASSABLE cell_99_99 -> GET snapshot 断言 cell_99_99 不在 hazards。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts_dir))
from _sandbox_client import get_bootstrapped_session  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="M14.4 soft hazard creation / PASSABLE no OPEN")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    session = get_bootstrapped_session(base, args.timeout)
    headers = {"X-JoyKey": "w1"}

    # 1) POST BLOCKED cell_12_34，合法 points_event_id -> 204
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={
            "segment_id": "cell_12_34",
            "segment_state": "BLOCKED",
            "points_event_id": "pe_m14_soft_01",
        },
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: POST segment_respond BLOCKED cell_12_34 -> expected 204, got {r.status_code}")
        print(r.text)
        return 1
    print("PASS: POST /v1/witness/segment_respond (cell_12_34 BLOCKED) -> 204")

    # 2) GET snapshot，断言 hazards 含 cell_12_34，SOFT_BLOCKED / SOFT_RECHECK / recheck_due_at 非空
    r = session.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL: GET snapshot -> {r.status_code}")
        return 1
    data = r.json()
    hazards = data.get("hazards") or []
    by_seg = {h["segment_id"]: h for h in hazards if isinstance(h, dict) and h.get("segment_id")}
    if "cell_12_34" not in by_seg:
        print("FAIL: hazards 中无 cell_12_34")
        print("hazards:", hazards)
        print("by_seg keys:", list(by_seg.keys()))
        return 1
    h = by_seg["cell_12_34"]
    if h.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL: hazard_status 应为 SOFT_BLOCKED，实际 {h.get('hazard_status')}")
        print("segment hazard dict:", h)
        return 1
    if h.get("hazard_lock_mode") != "SOFT_RECHECK":
        print(f"FAIL: hazard_lock_mode 应为 SOFT_RECHECK，实际 {h.get('hazard_lock_mode')}")
        print("segment hazard dict:", h)
        return 1
    recheck_due = h.get("recheck_due_at")
    if not recheck_due or not str(recheck_due).strip():
        print(f"FAIL: recheck_due_at 应为非空，实际 {recheck_due!r}")
        print("segment hazard dict:", h)
        return 1
    print(f"PASS: GET /v1/snapshot -> hazards 含 cell_12_34 hazard_status=SOFT_BLOCKED hazard_lock_mode=SOFT_RECHECK recheck_due_at={recheck_due}")

    # 3) POST PASSABLE cell_99_99（新 segment）-> 204
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        json={
            "segment_id": "cell_99_99",
            "segment_state": "PASSABLE",
            "points_event_id": "pe_m14_soft_02",
        },
        headers=headers,
        timeout=args.timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: POST segment_respond PASSABLE cell_99_99 -> expected 204, got {r.status_code}")
        print(r.text)
        return 1
    print("PASS: POST /v1/witness/segment_respond (cell_99_99 PASSABLE) -> 204")

    # 4) GET snapshot，断言 cell_99_99 不在 hazards（PASSABLE 不建 OPEN）
    r = session.get(f"{base}/v1/snapshot", timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL: GET snapshot (2) -> {r.status_code}")
        return 1
    data = r.json()
    hazards = data.get("hazards") or []
    seg_ids = [x.get("segment_id") for x in hazards if isinstance(x, dict)]
    if "cell_99_99" in seg_ids:
        print("FAIL: PASSABLE 不应新建 OPEN；cell_99_99 不应在 hazards 中")
        print("hazards segment_ids:", seg_ids)
        return 1
    print("PASS: GET /v1/snapshot -> cell_99_99 不在 hazards（PASSABLE 不创建 OPEN）")

    print("PASS: M14.4 soft hazard creation 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
