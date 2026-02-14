#!/usr/bin/env python3
"""
M15 验收：HARD_BLOCKED 仅能通过 POST /v1/work_orders/report work_order_status=DONE 解封。
1) 建立 segment 的 HARD_BLOCKED（witness BLOCKED 两轮 due 升级）。
2) 上报工单非 DONE（IN_PROGRESS），验证 snapshot 仍 HARD。
3) 调用 witness PASSABLE 或 telemetry segment_passed 尝试“清除”，验证仍 HARD。
4) 上报 work_order_status=DONE + segment_id，验证该 segment hazard 变为 OPEN。

运行建议：JOYGATE_SOFT_HAZARD_RECHECK_INTERVAL_MINUTES=1 JOYGATE_SOFT_HAZARD_ESCALATE_AFTER_RECHECKS=2。
         Demo 模式下设 JOYGATE_DEMO_MINUTE_SECONDS=5 时脚本会自动用 recheck_min*demo_minute_seconds+buffer 作为每轮 sleep（不传 --recheck_interval_sec 即可）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

import joygate.config  # ensure .env loaded

# 每轮唯一 segment，避免历史 segment_passed 导致 _recheck_verdict 判 PASSABLE
SEGMENT_PREFIX = "cell_15_"
BASE_URL_DEFAULT = "http://127.0.0.1:8000"
# Demo 模式下每轮 sleep 在 recheck_min*demo_minute_seconds 基础上的余量（秒）
RECHECK_SLEEP_BUFFER_SEC = 5


def main() -> int:
    p = argparse.ArgumentParser(description="M15 hard unlock only by work_order DONE")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT)
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument(
        "--recheck_interval_sec",
        type=float,
        default=None,
        help="每轮等 due 的秒数；未指定时：若 JOYGATE_DEMO_MINUTE_SECONDS!=60 则用 recheck_min*demo_minute_seconds+buffer，否则 70",
    )
    p.add_argument("--max_rounds", type=int, default=12, help="建立 HARD 最多轮数（5min recheck 约需 10 轮，1min 约 2～3 轮）")
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    max_rounds = max(2, args.max_rounds)
    # 唯一 segment 避免历史 segment_passed 导致复核判 PASSABLE
    segment_id = f"{SEGMENT_PREFIX}{int(time.time() * 1000)}"

    session = requests.Session()
    try:
        r = session.get(f"{base}/bootstrap", timeout=timeout)
    except requests.RequestException as e:
        print(f"FAIL: bootstrap failed: {e}")
        return 1
    if r.status_code != 200:
        print(f"FAIL: bootstrap status {r.status_code}")
        return 1

    # 默认每轮 sleep：若 Demo 模式（JOYGATE_DEMO_MINUTE_SECONDS!=60）则 recheck_min*demo_minute_seconds+buffer，否则 70
    if args.recheck_interval_sec is not None:
        interval_sec = max(5.0, args.recheck_interval_sec)
    else:
        raw = os.environ.get("JOYGATE_DEMO_MINUTE_SECONDS", "60") or "60"
        try:
            demo_minute_seconds = int(raw)
        except (ValueError, TypeError):
            demo_minute_seconds = 60
        if demo_minute_seconds <= 0:
            demo_minute_seconds = 60
        if demo_minute_seconds != 60:
            recheck_min = 5
            try:
                pol = session.get(f"{base}/v1/policy", timeout=timeout)
                if pol.status_code == 200 and isinstance(pol.json(), dict):
                    recheck_min = int(pol.json().get("soft_hazard_recheck_interval_minutes") or 5) or 5
            except Exception:
                pass
            interval_sec = max(5.0, float(recheck_min * demo_minute_seconds + RECHECK_SLEEP_BUFFER_SEC))
        else:
            interval_sec = 70.0

    # 1) 建立 HARD_BLOCKED：先 2 票 BLOCKED 建 SOFT，再多轮「等 due → 2 票 BLOCKED → GET」直到升级 HARD（兼容 1min witness 窗口下首轮 INCONCLUSIVE）
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={"segment_id": segment_id, "segment_state": "BLOCKED", "points_event_id": "pe_m15_1"},
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: witness BLOCKED #1 -> {r.status_code}")
        return 1
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={"segment_id": segment_id, "segment_state": "BLOCKED", "points_event_id": "pe_m15_2"},
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: witness BLOCKED #2 -> {r.status_code}")
        return 1
    work_order_id = None
    for round_no in range(1, max_rounds + 1):
        time.sleep(interval_sec)
        r = session.post(
            f"{base}/v1/witness/segment_respond",
            headers={"X-JoyKey": "w1"},
            json={"segment_id": segment_id, "segment_state": "BLOCKED", "points_event_id": f"pe_m15_r{round_no}_a"},
            timeout=timeout,
        )
        if r.status_code != 204:
            print(f"FAIL: witness BLOCKED round {round_no} #1 -> {r.status_code}")
            return 1
        r = session.post(
            f"{base}/v1/witness/segment_respond",
            headers={"X-JoyKey": "w1"},
            json={"segment_id": segment_id, "segment_state": "BLOCKED", "points_event_id": f"pe_m15_r{round_no}_b"},
            timeout=timeout,
        )
        if r.status_code != 204:
            print(f"FAIL: witness BLOCKED round {round_no} #2 -> {r.status_code}")
            return 1
        r = session.get(f"{base}/v1/snapshot", timeout=timeout)
        if r.status_code != 200:
            print(f"FAIL: GET snapshot -> {r.status_code}")
            return 1
        data = r.json()
        hazards = data.get("hazards") or []
        by_seg = {h["segment_id"]: h for h in hazards if h.get("segment_id")}
        if segment_id not in by_seg:
            continue
        h = by_seg[segment_id]
        if h.get("hazard_status") == "HARD_BLOCKED":
            work_order_id = h.get("work_order_id")
            break
    if not work_order_id:
        print("FAIL: 未在 max_rounds 内得到 HARD_BLOCKED；请增大 --recheck_interval_sec 或 --max_rounds")
        return 1
    if not work_order_id:
        print("FAIL: HARD 应有 work_order_id")
        return 1
    print("OK: 已建立 HARD_BLOCKED，work_order_id=", work_order_id)

    # 2) 上报工单非 DONE（IN_PROGRESS），snapshot 仍应为 HARD
    r = session.post(
        f"{base}/v1/work_orders/report",
        json={
            "work_order_id": work_order_id,
            "incident_id": None,
            "segment_id": segment_id,
            "charger_id": None,
            "work_order_status": "IN_PROGRESS",
            "event_occurred_at": time.time(),
            "evidence_refs": None,
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: work_orders/report IN_PROGRESS -> {r.status_code} {r.text[:200]}")
        return 1
    r = session.get(f"{base}/v1/snapshot", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET snapshot -> {r.status_code}")
        return 1
    by_seg = {h["segment_id"]: h for h in (r.json().get("hazards") or []) if h.get("segment_id")}
    if by_seg.get(segment_id, {}).get("hazard_status") != "HARD_BLOCKED":
        print("FAIL: 上报 IN_PROGRESS 后应仍为 HARD_BLOCKED")
        return 1
    print("OK: 上报 IN_PROGRESS 后 snapshot 仍 HARD_BLOCKED")

    # 3) witness PASSABLE + telemetry segment_passed，仍应为 HARD
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={
            "segment_id": segment_id,
            "segment_state": "PASSABLE",
            "points_event_id": "pe_m15_pass",
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: witness PASSABLE -> {r.status_code}")
        return 1
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "robot_m15",
            "fleet_id": None,
            "segment_ids": [segment_id],
            "event_occurred_at": time.time(),
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: telemetry segment_passed -> {r.status_code}")
        return 1
    r = session.get(f"{base}/v1/snapshot", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET snapshot -> {r.status_code}")
        return 1
    by_seg = {h["segment_id"]: h for h in (r.json().get("hazards") or []) if h.get("segment_id")}
    if by_seg.get(segment_id, {}).get("hazard_status") != "HARD_BLOCKED":
        print("FAIL: witness PASSABLE + telemetry 后应仍为 HARD_BLOCKED（不旁路解封）")
        return 1
    print("OK: witness PASSABLE + telemetry 后仍 HARD_BLOCKED")

    # 4) 上报 work_order_status=DONE + segment_id，应解封为 OPEN
    r = session.post(
        f"{base}/v1/work_orders/report",
        json={
            "work_order_id": work_order_id,
            "incident_id": None,
            "segment_id": segment_id,
            "charger_id": None,
            "work_order_status": "DONE",
            "event_occurred_at": time.time(),
            "evidence_refs": None,
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: work_orders/report DONE -> {r.status_code} {r.text[:200]}")
        return 1
    r = session.get(f"{base}/v1/snapshot", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET snapshot -> {r.status_code}")
        return 1
    by_seg = {h["segment_id"]: h for h in (r.json().get("hazards") or []) if h.get("segment_id")}
    if segment_id not in by_seg:
        print("OK: segment 解封后可能不在 hazards 列表（OPEN 可省略或仍返回）；检查 status")
    else:
        if by_seg[segment_id].get("hazard_status") != "OPEN":
            print(f"FAIL: 上报 DONE 后应为 OPEN，实际 {by_seg[segment_id].get('hazard_status')}")
            return 1
        print("OK: 上报 DONE 后 hazard 为 OPEN")

    # 若 OPEN 时 snapshot 仍含该 segment 且 status=OPEN，上面已断言；若实现为解封后从 hazards 移除，则 SEGMENT 可不在 by_seg
    print("")
    print("OK: M15 hard unlock only by work_order DONE 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
