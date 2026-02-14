#!/usr/bin/env python3
"""
M14.6 验收：两轮 SOFT 复核 BLOCKED（阈值=2）→ HARD_BLOCKED + work_order_id；
再喂 PASSABLE telemetry + PASSABLE witness 后 snapshot 仍为 HARD_BLOCKED（不自动解封）。
直接调用 store，不依赖运行中的服务。
"""
from __future__ import annotations

import os
import sys
import time

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src = os.path.join(_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import joygate.config  # ensure .env loaded

os.environ.setdefault("JOYGATE_SOFT_HAZARD_RECHECK_INTERVAL_MINUTES", "1")
os.environ.setdefault("JOYGATE_SOFT_HAZARD_ESCALATE_AFTER_RECHECKS", "2")
os.environ.setdefault("JOYGATE_SEGMENT_WITNESS_SLA_TIMEOUT_MINUTES", "5")
os.environ.setdefault("JOYGATE_SEGMENT_WITNESS_VOTES_REQUIRED", "2")

from joygate.store import JoyGateStore, _iso_utc  # noqa: E402


def main() -> int:
    store = JoyGateStore()
    now = time.time()
    seg = "cell_12_34"

    # 1) 造 SOFT_BLOCKED，recheck_due_at 已过期
    store._hazards_by_segment[seg] = {
        "segment_id": seg,
        "hazard_status": "SOFT_BLOCKED",
        "hazard_lock_mode": "SOFT_RECHECK",
        "recheck_due_at": _iso_utc(now - 60),
        "recheck_interval_minutes": 1,
        "soft_recheck_consecutive_blocked": 0,
        "work_order_id": None,
        "hazard_id": "haz_test",
    }
    store._segment_witness_events.extend([
        {"segment_id": seg, "segment_state": "BLOCKED", "ts": now},
        {"segment_id": seg, "segment_state": "BLOCKED", "ts": now},
    ])

    with store._lock:
        store._process_due_soft_rechecks_locked(now)
    rec = store._hazards_by_segment.get(seg) or {}
    if rec.get("soft_recheck_consecutive_blocked") != 1 or rec.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL: 第一轮 BLOCKED 后应为 consecutive=1 且仍 SOFT_BLOCKED，实际 {rec.get('soft_recheck_consecutive_blocked')} / {rec.get('hazard_status')}")
        return 1
    print("PASS: 第一轮 BLOCKED -> consecutive=1, 仍 SOFT_BLOCKED")

    # 2) 再排 due 已过期，再判 BLOCKED -> consecutive=2 -> 升级 HARD
    rec["recheck_due_at"] = _iso_utc(now - 30)
    store._segment_witness_events.extend([
        {"segment_id": seg, "segment_state": "BLOCKED", "ts": now + 1},
        {"segment_id": seg, "segment_state": "BLOCKED", "ts": now + 1},
    ])
    with store._lock:
        store._process_due_soft_rechecks_locked(now + 2)
    rec = store._hazards_by_segment.get(seg) or {}
    if rec.get("hazard_status") != "HARD_BLOCKED":
        print(f"FAIL: 第二轮后应为 HARD_BLOCKED，实际 {rec.get('hazard_status')}")
        return 1
    if rec.get("hazard_lock_mode") != "HARD_MANUAL":
        print(f"FAIL: hazard_lock_mode 应为 HARD_MANUAL，实际 {rec.get('hazard_lock_mode')}")
        return 1
    wo = rec.get("work_order_id")
    if not wo or not str(wo).startswith("wo_"):
        print(f"FAIL: work_order_id 应为 wo_xxx，实际 {wo!r}")
        return 1
    print("PASS: 第二轮 BLOCKED -> HARD_BLOCKED, HARD_MANUAL, work_order_id=", wo)

    # 3) snapshot 中见 HARD_BLOCKED / HARD_MANUAL / work_order_id != null
    snap = store.snapshot()
    hazards = snap.get("hazards") or []
    by_seg = {h["segment_id"]: h for h in hazards if h.get("segment_id")}
    if seg not in by_seg:
        print("FAIL: snapshot hazards 应含 segment")
        return 1
    h = by_seg[seg]
    if h.get("hazard_status") != "HARD_BLOCKED":
        print(f"FAIL: snapshot hazard_status 应为 HARD_BLOCKED，实际 {h.get('hazard_status')}")
        return 1
    if h.get("hazard_lock_mode") != "HARD_MANUAL":
        print(f"FAIL: snapshot hazard_lock_mode 应为 HARD_MANUAL，实际 {h.get('hazard_lock_mode')}")
        return 1
    if h.get("work_order_id") is None or h.get("work_order_id") == "":
        print("FAIL: snapshot work_order_id 应非空")
        return 1
    print("PASS: snapshot 中 hazard_status=HARD_BLOCKED, hazard_lock_mode=HARD_MANUAL, work_order_id!=null")

    # 4) 喂 PASSABLE telemetry + PASSABLE witness，再 snapshot -> 仍 HARD_BLOCKED
    t_now = time.time()
    store.record_segment_passed_telemetry(
        joykey="robot_01",
        fleet_id="fleet_01",
        segment_ids=[seg],
        event_occurred_at=t_now,
        truth_input_source="SIMULATOR",
    )
    store.record_segment_witness(
        segment_id=seg,
        segment_state="PASSABLE",
        witness_joykey="w1",
        points_event_id="pe_pass_01",
    )
    snap2 = store.snapshot()
    hazards2 = snap2.get("hazards") or []
    by_seg2 = {x["segment_id"]: x for x in hazards2 if x.get("segment_id")}
    if seg not in by_seg2:
        print("FAIL: 喂 PASSABLE 后 snapshot 仍应含该 segment hazard")
        return 1
    h2 = by_seg2[seg]
    if h2.get("hazard_status") != "HARD_BLOCKED":
        print(f"FAIL: 喂 PASSABLE 后应仍为 HARD_BLOCKED（不自动解封），实际 {h2.get('hazard_status')}")
        return 1
    print("PASS: 喂 PASSABLE telemetry + PASSABLE witness 后 snapshot 仍 HARD_BLOCKED（不自动解封）")

    print("PASS: M14.6 两轮 BLOCKED -> HARD + work_order_id，PASSABLE 不自动解封，全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
