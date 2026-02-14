from __future__ import annotations

import time

from joygate.store import JoyGateStore


def _get_internal_incident(store: JoyGateStore, incident_id: str) -> dict:
    for r in store._incidents:  # noqa: SLF001 (unit test reads internal state)
        if r.get("incident_id") == incident_id:
            return r
    raise AssertionError(f"incident not found in store._incidents: {incident_id}")


def main() -> None:
    store = JoyGateStore()

    # 1) 创建一个 incident（OPEN）
    incident_id = store.report_blocked_incident(
        charger_id="charger-001",
        incident_type="BLOCKED",
        snapshot_ref=None,
        evidence_refs=["ev:init_1", "ev:init_2", "ev:init_3", "ev:init_4", "ev:init_5", "ev:init_6"],
    )

    # report_blocked_incident 已限制 evidence_refs <= 5
    inc0 = _get_internal_incident(store, incident_id)
    assert len(inc0.get("evidence_refs") or []) == 5, "report_blocked_incident evidence cap failed"

    # 2) 非白名单 witness 应拒绝
    try:
        store.witness_respond(
            witness_joykey="not_allowed",
            incident_id=incident_id,
            charger_id="charger-001",
            charger_state="OCCUPIED",
            obstacle_type=None,
            evidence_refs=["ev:x"],
            points_event_id="evt_x",
        )
        raise AssertionError("non-allowlisted witness should raise PermissionError")
    except PermissionError:
        pass

    # 3) charger_state 非法应拒绝
    try:
        store.witness_respond(
            witness_joykey="w1",
            incident_id=incident_id,
            charger_id="charger-001",
            charger_state="INVALID_STATE",
            obstacle_type=None,
            evidence_refs=["ev:x"],
            points_event_id="evt_bad_state",
        )
        raise AssertionError("invalid charger_state should raise ValueError")
    except ValueError:
        pass

    # 4) w1 首投：应计票 + 证据合并（仍 capped 到 5）
    store.witness_respond(
        witness_joykey="w1",
        incident_id=incident_id,
        charger_id="charger-001",
        charger_state="OCCUPIED",
        obstacle_type="CAR",
        evidence_refs=["ev:w1_1", "ev:w1_2"],
        points_event_id="  evt_w1_1  ",  # 测试 strip 归一化
    )
    inc1 = _get_internal_incident(store, incident_id)
    assert inc1.get("incident_status") == "OPEN", "should still be OPEN after 1 vote (default threshold=2)"
    assert len(inc1.get("evidence_refs") or []) <= 5, "evidence_refs must be capped to 5"
    assert any((x.get("insight_type") == "WITNESS_TALLY") for x in (inc1.get("ai_insights") or [])), "missing WITNESS_TALLY"

    # 5) w1 重复投票：不应计票；但如果带新的 points_event_id，应该只补记一次（不计票）
    w_before = store._witness_by_incident[incident_id]["total"]  # noqa: SLF001
    store.witness_respond(
        witness_joykey="w1",
        incident_id=incident_id,
        charger_id="charger-001",
        charger_state="OCCUPIED",
        obstacle_type="CAR",
        evidence_refs=["ev:w1_dup_should_not_append"],
        points_event_id="evt_w1_dup_newid",
    )
    w_after = store._witness_by_incident[incident_id]["total"]  # noqa: SLF001
    assert w_before == w_after, "duplicate witness vote should not increase total"

    # 6) w2 第二票：应推进到 EVIDENCE_CONFIRMED（默认阈值最小为 2）
    store.witness_respond(
        witness_joykey="w2",
        incident_id=incident_id,
        charger_id="charger-001",
        charger_state="OCCUPIED",
        obstacle_type="CAR",
        evidence_refs=["ev:w2_1"],
        points_event_id="evt_w2_1",
    )
    inc2 = _get_internal_incident(store, incident_id)
    assert inc2.get("incident_status") == "EVIDENCE_CONFIRMED", "should become EVIDENCE_CONFIRMED after reaching threshold"
    ts_confirmed = inc2.get("status_updated_at")

    # 7) 已 EVIDENCE_CONFIRMED 后，再来新 witness（alpha_02）：
    # - 仍可更新 tally/ai_insights/证据（但证据仍 capped）
    # - 不应刷新 status_updated_at
    time.sleep(0.02)
    store.witness_respond(
        witness_joykey="alpha_02",
        incident_id=incident_id,
        charger_id="charger-001",
        charger_state="OCCUPIED",
        obstacle_type="CAR",
        evidence_refs=["ev:alpha_1", "ev:alpha_2", "ev:alpha_3"],
        points_event_id="evt_alpha_1",
    )
    inc3 = _get_internal_incident(store, incident_id)
    assert inc3.get("incident_status") == "EVIDENCE_CONFIRMED", "status should remain EVIDENCE_CONFIRMED"
    assert inc3.get("status_updated_at") == ts_confirmed, "status_updated_at must NOT refresh when already EVIDENCE_CONFIRMED"
    assert len(inc3.get("evidence_refs") or []) <= 5, "evidence_refs must be capped to 5"

    # 8) list_incidents：不泄露 created_at/status_updated_at，且仍是 8 字段口径
    out = store.list_incidents(incident_id=incident_id)
    assert len(out) == 1
    item = out[0]
    assert "created_at" not in item, "list_incidents must not expose created_at"
    assert "status_updated_at" not in item, "list_incidents must not expose status_updated_at"

    expected_keys = {
        "incident_id",
        "incident_type",
        "incident_status",
        "charger_id",
        "segment_id",
        "snapshot_ref",
        "evidence_refs",
        "ai_insights",
    }
    assert set(item.keys()) == expected_keys, f"IncidentItem keys mismatch: {set(item.keys())}"

    print("OK: witness voting semantics (8.1 store-level) passed.")


if __name__ == "__main__":
    main()
