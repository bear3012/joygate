#!/usr/bin/env python3
"""
M16 验收：信誉计分与可验证事件闭环。
1) 创建 incident（POST /v1/incidents/report_blocked）
2) 用默认 witness joykeys（w1, w2）投票直到 incident_status == EVIDENCE_CONFIRMED
3) GET /v1/reputation、/v1/score_events、/v1/vendor_scores
4) 断言：至少一个 witness 的 robot_score 从 60 增至 62；score_events 含 WITNESS_VOTE_VERIFIED
5) 重复发送最后一票（同 points_event_id），断言 score_events 数量不增加（幂等）
"""
from __future__ import annotations

import argparse
import sys

import requests

import joygate.config  # ensure .env loaded

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
CHARGER_ID = "charger-001"
INCIDENT_TYPE = "BLOCKED"
WITNESS_JOYKEYS = ["w1", "w2"]
CHARGER_STATE = "OCCUPIED"


def _verified_event_ids(events: list[dict], incident_id: str) -> set[str]:
    """本次 incident 的 verified 事件 id 集合：仅 WITNESS_VOTE_VERIFIED 且 score_incident_id/incident_id 匹配。"""
    out: set[str] = set()
    for e in events:
        if e.get("score_event_type") != "WITNESS_VOTE_VERIFIED":
            continue
        eid_inc = e.get("score_incident_id") or e.get("incident_id") or ""
        if eid_inc != incident_id:
            continue
        sid = e.get("score_event_id") or e.get("event_id")
        if isinstance(sid, str) and sid.strip():
            out.add(sid)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="M16 reputation scoring: witness verified -> score event")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT)
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # bootstrap
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}")
        return 1

    # 1) 创建 incident
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": CHARGER_ID, "incident_type": INCIDENT_TYPE},
        timeout=timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: report_blocked {r.status_code} {r.text[:200]}")
        return 1
    incident_id = r.json().get("incident_id")
    if not incident_id:
        print("FAIL: no incident_id in response")
        return 1
    print(f"OK: incident_id={incident_id}")

    # 2) witness 投票直到 EVIDENCE_CONFIRMED（w1 + w2 各一票 OCCUPIED，两厂商即达阈值）
    for i, joykey in enumerate(WITNESS_JOYKEYS):
        r = session.post(
            f"{base}/v1/witness/respond",
            headers={"X-JoyKey": joykey},
            json={
                "incident_id": incident_id,
                "charger_id": CHARGER_ID,
                "charger_state": CHARGER_STATE,
                "points_event_id": f"pe_m16_{incident_id}_{i}",
            },
            timeout=timeout,
        )
        if r.status_code != 204:
            print(f"FAIL: witness {joykey} -> {r.status_code} {r.text[:200]}")
            return 1
    r = session.get(f"{base}/v1/incidents", params={"incident_id": incident_id}, timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET incidents {r.status_code}")
        return 1
    items = r.json().get("incidents") or []
    inc = next((x for x in items if x.get("incident_id") == incident_id), None)
    if not inc:
        print("FAIL: incident not found after votes")
        return 1
    status = inc.get("incident_status")
    if status != "EVIDENCE_CONFIRMED":
        print(f"FAIL: expected EVIDENCE_CONFIRMED, got incident_status={status}")
        return 1
    print("OK: incident_status=EVIDENCE_CONFIRMED")

    # 3) GET reputation / score_events / vendor_scores
    scores_after: dict[str, int] = {}
    for joykey in WITNESS_JOYKEYS:
        r = session.get(f"{base}/v1/reputation", params={"joykey": joykey}, timeout=timeout)
        if r.status_code == 404:
            print(f"FAIL: reputation 404 for joykey={joykey} (expected record after verified)")
            return 1
        if r.status_code != 200:
            print(f"FAIL: GET reputation {r.status_code} {r.text[:200]}")
            return 1
        rep = r.json()
        raw = rep.get("robot_score")
        scores_after[joykey] = int(raw) if raw is not None else 0
    r = session.get(f"{base}/v1/score_events", params={"limit": 50}, timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET score_events {r.status_code}")
        return 1
    events = r.json().get("score_events") or []
    r = session.get(f"{base}/v1/vendor_scores", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET vendor_scores {r.status_code}")
        return 1
    vendors = r.json().get("vendor_scores") or []

    # 4) 断言：至少一个 witness robot_score >= 62（60 + SCORE_DELTA_WITNESS_VERIFIED）
    any_increased = any(s >= 62 for s in scores_after.values())
    if not any_increased:
        print(f"FAIL: no witness robot_score >= 62; got {scores_after}")
        return 1
    has_verified = len(_verified_event_ids(events, incident_id)) > 0
    if not has_verified:
        print(f"FAIL: no WITNESS_VOTE_VERIFIED for this incident in score_events; types={[e.get('score_event_type') for e in events]}")
        return 1
    print(f"OK: robot_scores={scores_after}, score_events count={len(events)}, vendor_scores count={len(vendors)}")

    # 5) 幂等：重发最后一票（同 incident、同 joykey、同 points_event_id），本 incident 的 verified 事件集合不应增加
    before_set = _verified_event_ids(events, incident_id)
    r = session.post(
        f"{base}/v1/witness/respond",
        headers={"X-JoyKey": WITNESS_JOYKEYS[-1]},
        json={
            "incident_id": incident_id,
            "charger_id": CHARGER_ID,
            "charger_state": CHARGER_STATE,
            "points_event_id": f"pe_m16_{incident_id}_{len(WITNESS_JOYKEYS)-1}",
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: repeat witness -> {r.status_code}")
        return 1
    r = session.get(f"{base}/v1/score_events", params={"limit": 50}, timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET score_events after repeat {r.status_code}")
        return 1
    events_after = r.json().get("score_events") or []
    after_set = _verified_event_ids(events_after, incident_id)
    if len(after_set) > len(before_set):
        print(f"FAIL: idempotency violated: verified event ids for this incident grew; new ids={sorted(after_set - before_set)}")
        return 1
    print("OK: idempotency verified (verified event set for this incident unchanged after repeat vote)")

    print("OK: M16 reputation scoring full pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
