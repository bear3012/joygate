#!/usr/bin/env python3
"""
M14 可复审证据闭环：SOFT 复核三分支。
Case A：witness BLOCKED → SOFT_BLOCKED；telemetry PASSABLE（freshness 窗口内）→ due 后 snapshot → hazard OPEN。
Case B：witness BLOCKED → due 到期但票数不足/平票 → INCONCLUSIVE → 仍 SOFT_BLOCKED，due 后移。
Case C：witness BLOCKED → 连续 BLOCKED 达阈值 → HARD_BLOCKED + work_order_id。
直接调 store，不依赖运行中的服务。
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
os.environ.setdefault("JOYGATE_SEGMENT_WITNESS_VOTES_REQUIRED", "2")
os.environ.setdefault("JOYGATE_SEGMENT_WITNESS_SLA_TIMEOUT_MINUTES", "5")
os.environ.setdefault("JOYGATE_SEGMENT_FRESHNESS_WINDOW_MINUTES", "10")

from joygate.store import JoyGateStore, _iso_utc  # noqa: E402


def main() -> int:
    now = time.time()
    seg_a = "cell_1_1"
    seg_b = "cell_2_2"
    seg_c = "cell_3_3"

    # ---- Case A：BLOCKED → telemetry PASSABLE（窗口内）→ due 后 snapshot → OPEN ----
    store_a = JoyGateStore()
    store_a.record_segment_witness(
        segment_id=seg_a,
        segment_state="BLOCKED",
        witness_joykey="w1",
        points_event_id="pe_a1",
    )
    rec_a = store_a._hazards_by_segment.get(seg_a) or {}
    if rec_a.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL Case A setup: hazard_status 应为 SOFT_BLOCKED，实际 {rec_a.get('hazard_status')}")
        return 1
    store_a.record_segment_passed_telemetry(
        joykey="robot_a",
        fleet_id="fleet_a",
        segment_ids=[seg_a],
        event_occurred_at=now,
        truth_input_source="SIMULATOR",
    )
    rec_a = store_a._hazards_by_segment.get(seg_a) or {}
    rec_a["recheck_due_at"] = _iso_utc(now - 60)
    store_a._hazards_by_segment[seg_a] = rec_a
    snap_a = store_a.snapshot()
    hazards_a = snap_a.get("hazards") or []
    by_seg_a = {h["segment_id"]: h for h in hazards_a if h.get("segment_id")}
    if seg_a not in by_seg_a:
        print("FAIL Case A: snapshot 应含 segment")
        return 1
    if by_seg_a[seg_a].get("hazard_status") != "OPEN":
        print(f"FAIL Case A: due 后 telemetry PASSABLE 应为 OPEN，实际 {by_seg_a[seg_a].get('hazard_status')}")
        return 1
    print("PASS Case A: witness BLOCKED → telemetry PASSABLE（窗口内）→ due 后 snapshot → hazard OPEN")

    # ---- Case B：BLOCKED → due 到期但票数不足 → INCONCLUSIVE → 仍 SOFT_BLOCKED，due 后移 ----
    store_b = JoyGateStore()
    store_b.record_segment_witness(
        segment_id=seg_b,
        segment_state="BLOCKED",
        witness_joykey="w1",
        points_event_id="pe_b1",
    )
    rec_b = store_b._hazards_by_segment.get(seg_b) or {}
    rec_b["recheck_due_at"] = _iso_utc(now - 60)
    store_b._hazards_by_segment[seg_b] = rec_b
    snap_b = store_b.snapshot()
    hazards_b = snap_b.get("hazards") or []
    by_seg_b = {h["segment_id"]: h for h in hazards_b if h.get("segment_id")}
    if seg_b not in by_seg_b:
        print("FAIL Case B: snapshot 应含 segment")
        return 1
    h_b = by_seg_b[seg_b]
    if h_b.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL Case B: 票数不足应为 INCONCLUSIVE → 仍 SOFT_BLOCKED，实际 {h_b.get('hazard_status')}")
        return 1
    if not h_b.get("recheck_due_at") or not str(h_b.get("recheck_due_at", "")).strip():
        print("FAIL Case B: INCONCLUSIVE 应重排 recheck_due_at")
        return 1
    if (h_b.get("soft_recheck_consecutive_blocked") or 0) != 0:
        print(f"FAIL Case B: INCONCLUSIVE 不应增加 consecutive，实际 {h_b.get('soft_recheck_consecutive_blocked')}")
        return 1
    print("PASS Case B: witness BLOCKED → due 到期票数不足 → INCONCLUSIVE → 仍 SOFT_BLOCKED，due 后移")

    # ---- Case C：BLOCKED → 连续 BLOCKED 达阈值 → HARD_BLOCKED + work_order_id ----
    store_c = JoyGateStore()
    store_c.record_segment_witness(
        segment_id=seg_c,
        segment_state="BLOCKED",
        witness_joykey="w1",
        points_event_id="pe_c1",
    )
    rec_c = store_c._hazards_by_segment.get(seg_c) or {}
    rec_c["recheck_due_at"] = _iso_utc(now - 60)
    store_c._segment_witness_events.extend([
        {"segment_id": seg_c, "segment_state": "BLOCKED", "ts": now},
        {"segment_id": seg_c, "segment_state": "BLOCKED", "ts": now},
    ])
    store_c._hazards_by_segment[seg_c] = rec_c
    with store_c._lock:
        store_c._process_due_soft_rechecks_locked(now)
    rec_c = store_c._hazards_by_segment.get(seg_c) or {}
    if rec_c.get("soft_recheck_consecutive_blocked") != 1 or rec_c.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL Case C 第一轮: 应为 consecutive=1 仍 SOFT，实际 {rec_c.get('soft_recheck_consecutive_blocked')} / {rec_c.get('hazard_status')}")
        return 1
    rec_c["recheck_due_at"] = _iso_utc(now - 30)
    store_c._segment_witness_events.extend([
        {"segment_id": seg_c, "segment_state": "BLOCKED", "ts": now + 1},
        {"segment_id": seg_c, "segment_state": "BLOCKED", "ts": now + 1},
    ])
    with store_c._lock:
        store_c._process_due_soft_rechecks_locked(now + 2)
    rec_c = store_c._hazards_by_segment.get(seg_c) or {}
    if rec_c.get("hazard_status") != "HARD_BLOCKED":
        print(f"FAIL Case C: 两轮 BLOCKED 应为 HARD_BLOCKED，实际 {rec_c.get('hazard_status')}")
        return 1
    if rec_c.get("hazard_lock_mode") != "HARD_MANUAL":
        print(f"FAIL Case C: hazard_lock_mode 应为 HARD_MANUAL，实际 {rec_c.get('hazard_lock_mode')}")
        return 1
    wo = rec_c.get("work_order_id")
    if not wo or not str(wo).startswith("wo_"):
        print(f"FAIL Case C: work_order_id 应为 wo_xxx，实际 {wo!r}")
        return 1
    print("PASS Case C: witness BLOCKED → 连续 BLOCKED 达阈值 → HARD_BLOCKED + work_order_id")

    print("")
    print("PASS: M14 soft recheck cycle A/B/C 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
