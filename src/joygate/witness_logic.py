from __future__ import annotations

import time
from typing import Any

# evidence_refs 防污染：最多 5 条，每项 str、strip 非空、长度<=120
EVIDENCE_REFS_MAX = 5
EVIDENCE_REF_MAX_LEN = 120


def _normalize_evidence_refs(refs: list[str] | None) -> list[str]:
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for r in refs:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if not s or len(s) > EVIDENCE_REF_MAX_LEN:
            continue
        out.append(s)
        if len(out) >= EVIDENCE_REFS_MAX:
            break
    return out


def witness_respond_locked(
    incidents: list[dict[str, Any]],
    witness_by_incident: dict[str, dict[str, Any]],
    incident_id: str,
    charger_id: str,
    charger_state: str,
    obstacle_type: str | None,
    evidence_refs: list[str] | None,
    points_event_id: str | None,
    witness_joykey: str,
    allowed_states: set[str],
    joykey_to_vendor: dict[str, str],
    joykey_to_points: dict[str, int],
    witness_vendor_decay_gamma: float,
    witness_min_distinct_vendors: int,
    witness_score_required: float,
    witness_score_required_single_vendor: float,
    witness_min_distinct_vendors_risky: int,
    witness_score_required_risky: float,
    witness_min_margin_risky: float,
    witness_certified_points_threshold: int,
    witness_min_certified_support_risky: int,
) -> None:
    rec = None
    for r in incidents:
        if r.get("incident_id") == incident_id:
            rec = r
            break
    if rec is None:
        raise KeyError(f"incident not found: {incident_id}")
    inc_charger_id = rec.get("charger_id")
    if not inc_charger_id or inc_charger_id != charger_id:
        raise ValueError(f"incident charger_id mismatch: incident={inc_charger_id!r}, request={charger_id!r}")

    if incident_id not in witness_by_incident:
        witness_by_incident[incident_id] = {
            "tally": {"FREE": 0, "OCCUPIED": 0, "UNKNOWN_OCCUPANCY": 0},
            "tally_weighted": {"FREE": 0.0, "OCCUPIED": 0.0, "UNKNOWN_OCCUPANCY": 0.0},
            "vendor_vote_counts": {},  # vendor -> count（同厂指数衰减）
            "vendors_by_state": {"FREE": set(), "OCCUPIED": set(), "UNKNOWN_OCCUPANCY": set()},
            "certified_witnesses_by_state": {"FREE": set(), "OCCUPIED": set(), "UNKNOWN_OCCUPANCY": set()},
            "seen_points_event_ids": set(),
            "seen_witness_joykeys": set(),
            "witness_points_event_id": {},  # witness_joykey -> points_event_id（防呆：避免无限增长）
            "total": 0,
        }
    w = witness_by_incident[incident_id]
    # 兼容旧结构：补齐/修复 vendors_by_state，防止 KeyError
    if not isinstance(w.get("vendors_by_state"), dict):
        w["vendors_by_state"] = {"FREE": set(), "OCCUPIED": set(), "UNKNOWN_OCCUPANCY": set()}
    else:
        for state_key in ("FREE", "OCCUPIED", "UNKNOWN_OCCUPANCY"):
            if not isinstance(w["vendors_by_state"].get(state_key), set):
                w["vendors_by_state"][state_key] = set()
    # 兼容旧结构：补齐/修复 certified_witnesses_by_state，防止 KeyError
    if not isinstance(w.get("certified_witnesses_by_state"), dict):
        w["certified_witnesses_by_state"] = {
            "FREE": set(),
            "OCCUPIED": set(),
            "UNKNOWN_OCCUPANCY": set(),
        }
    else:
        for state_key in ("FREE", "OCCUPIED", "UNKNOWN_OCCUPANCY"):
            if not isinstance(w["certified_witnesses_by_state"].get(state_key), set):
                w["certified_witnesses_by_state"][state_key] = set()

    if charger_state not in allowed_states:
        raise ValueError(f"invalid charger_state: {charger_state!r}")

    if witness_joykey in w["seen_witness_joykeys"]:
        return  # witness_joykey 去重强制生效，不看 points_event_id，防止刷票

    if points_event_id:
        if points_event_id in w["seen_points_event_ids"]:
            return
        w["seen_points_event_ids"].add(points_event_id)

    w["seen_witness_joykeys"].add(witness_joykey)
    vendor = joykey_to_vendor.get(witness_joykey) or "unknown"
    vendor_counts = w.get("vendor_vote_counts") or {}
    vendor_count = int(vendor_counts.get(vendor, 0))
    weight = witness_vendor_decay_gamma**vendor_count
    vendor_counts[vendor] = vendor_count + 1
    w["vendor_vote_counts"] = vendor_counts
    w["vendors_by_state"][charger_state].add(vendor)
    points = joykey_to_points.get(witness_joykey, 0)
    if points >= witness_certified_points_threshold:
        w["certified_witnesses_by_state"][charger_state].add(witness_joykey)
    w["tally"][charger_state] = w["tally"].get(charger_state, 0) + 1
    w["tally_weighted"][charger_state] = w["tally_weighted"].get(charger_state, 0.0) + weight
    w["total"] = w["total"] + 1

    if evidence_refs:
        existing = _normalize_evidence_refs(rec.get("evidence_refs"))
        incoming = _normalize_evidence_refs(evidence_refs)
        seen = set(existing)
        for ref in incoming:
            if ref not in seen:
                existing.append(ref)
                seen.add(ref)
        rec["evidence_refs"] = existing[:EVIDENCE_REFS_MAX]

    total = w["total"]
    tally = w["tally"]
    tally_weighted = w["tally_weighted"]
    lead_state = max(tally_weighted, key=lambda k: tally_weighted[k])
    lead_weighted = tally_weighted.get(lead_state, 0.0)
    sorted_weighted = sorted(tally_weighted.values(), reverse=True)
    second_weighted = sorted_weighted[1] if len(sorted_weighted) > 1 else 0.0
    margin = lead_weighted - second_weighted
    sum_weighted = sum(tally_weighted.values())
    distinct_vendors = len(w.get("vendor_vote_counts") or {})
    summary = (
        "witness tally: "
        f"FREE={tally.get('FREE',0)} OCCUPIED={tally.get('OCCUPIED',0)} "
        f"UNKNOWN_OCCUPANCY={tally.get('UNKNOWN_OCCUPANCY',0)} | "
        f"wFREE={tally_weighted.get('FREE',0.0):.2f} "
        f"wOCCUPIED={tally_weighted.get('OCCUPIED',0.0):.2f} "
        f"wUNKNOWN_OCCUPANCY={tally_weighted.get('UNKNOWN_OCCUPANCY',0.0):.2f} | "
        f"lead={lead_state} w={lead_weighted:.2f} "
        f"vendors={distinct_vendors} gamma={witness_vendor_decay_gamma:.2f}"
    )
    confidence = int(lead_weighted * 100 / sum_weighted) if sum_weighted > 0 else None
    insight = {
        "insight_type": "WITNESS_TALLY",
        "summary": summary,
        "confidence": confidence,
        "obstacle_type": obstacle_type,
        "sample_index": None,
        "ai_report_id": None,
    }
    ai_insights = rec.get("ai_insights") or []
    replaced = False
    for i, item in enumerate(ai_insights):
        if isinstance(item, dict) and item.get("insight_type") == "WITNESS_TALLY":
            ai_insights[i] = insight
            replaced = True
            break
    if not replaced:
        ai_insights.append(insight)
    rec["ai_insights"] = ai_insights

    if lead_state == "UNKNOWN_OCCUPANCY":
        certified_support = len(w.get("certified_witnesses_by_state", {}).get("UNKNOWN_OCCUPANCY") or set())
        support_vendors = len(w.get("vendors_by_state", {}).get("UNKNOWN_OCCUPANCY") or set())
        reach_confirm = (
            support_vendors >= witness_min_distinct_vendors_risky
            and lead_weighted >= witness_score_required_risky
            and margin >= witness_min_margin_risky
            and certified_support >= witness_min_certified_support_risky
        )
    else:
        if distinct_vendors >= witness_min_distinct_vendors:
            reach_confirm = lead_weighted >= witness_score_required
        else:
            reach_confirm = lead_weighted >= witness_score_required_single_vendor

    if reach_confirm:
        current_status = rec.get("incident_status")
        if current_status not in ("EVIDENCE_CONFIRMED", "RESOLVED"):
            rec["incident_status"] = "EVIDENCE_CONFIRMED"
            rec["status_updated_at"] = time.time()
        # 如果已经是 EVIDENCE_CONFIRMED 或 RESOLVED：保持 status_updated_at 不变，不重复刷新
