from __future__ import annotations

import time
import uuid
from typing import Any

from joygate.config import minute_to_seconds

# evidence_refs 防污染：最多 5 条，每项 str、strip 非空、长度<=120（与 witness_logic 一致）
_EVIDENCE_REFS_MAX = 5
_EVIDENCE_REF_MAX_LEN = 120


def _normalize_evidence_refs(refs: list[str] | None) -> list[str]:
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for r in refs:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if not s or len(s) > _EVIDENCE_REF_MAX_LEN:
            continue
        out.append(s)
        if len(out) >= _EVIDENCE_REFS_MAX:
            break
    return out


def cleanup_incidents_locked(
    incidents: list[dict[str, Any]],
    witness_by_incident: dict[str, dict[str, Any]],
    now: float,
    max_incidents: int,
    ttl_resolved_low_seconds: int,
    ttl_resolved_high_seconds: int,
    low_retention_incident_types: set[str],
) -> None:
    # 阶段1：TTL 清理
    def should_delete(rec: dict[str, Any]) -> bool:
        if rec.get("incident_status") != "RESOLVED":
            return False
        base_ts = rec.get("status_updated_at") or rec.get("created_at", 0.0)
        ttl = (
            ttl_resolved_low_seconds
            if rec.get("incident_type") in low_retention_incident_types
            else ttl_resolved_high_seconds
        )
        return (now - base_ts) > ttl

    new_list = [rec for rec in incidents if not should_delete(rec)]
    incidents[:] = new_list

    # 阶段2：硬上限（写入前腾出空间，保证 append 后不超过 MAX_INCIDENTS）
    while len(incidents) >= max_incidents:
        idx = None
        for i, rec in enumerate(incidents):
            if rec.get("incident_status") == "RESOLVED":
                idx = i
                break
        if idx is not None:
            incidents.pop(idx)
        else:
            incidents.pop(0)

    # 联动清理：删除已移除 incident 的 witness 数据，防内存泄露
    remaining_ids = {r.get("incident_id") for r in incidents}
    for iid in list(witness_by_incident.keys()):
        if iid not in remaining_ids:
            del witness_by_incident[iid]


def apply_witness_sla_downgrade_locked(
    incidents: list[dict[str, Any]],
    witness_by_incident: dict[str, dict[str, Any]],
    now: float,
    witness_sla_timeout_minutes: float,
) -> None:
    if witness_sla_timeout_minutes <= 0:
        return
    sla_seconds = minute_to_seconds(witness_sla_timeout_minutes)
    for rec in incidents:
        status = rec.get("incident_status")
        if status in ("RESOLVED", "EVIDENCE_CONFIRMED"):
            continue
        created_at = rec.get("created_at")
        if not created_at:
            continue
        if (now - created_at) < sla_seconds:
            continue

        if status == "OPEN":
            rec["incident_status"] = "UNDER_OBSERVATION"
            rec["status_updated_at"] = now

        incident_id = rec.get("incident_id")
        votes_seen = 0
        if incident_id:
            w = witness_by_incident.get(incident_id)
            if w:
                votes_seen = int(w.get("total") or 0)

        summary = (
            f"witness SLA timeout: {witness_sla_timeout_minutes}m, "
            f"votes_seen={votes_seen}, not confirmed -> downgrade triggered"
        )
        insight = {
            "insight_type": "VISION_AUDIT_REQUESTED",
            "summary": summary,
            "confidence": None,
            "obstacle_type": None,
            "sample_index": None,
            "ai_report_id": None,
        }
        ai_insights = rec.get("ai_insights") or []
        replaced = False
        for i, item in enumerate(ai_insights):
            if isinstance(item, dict) and item.get("insight_type") == "VISION_AUDIT_REQUESTED":
                ai_insights[i] = insight
                replaced = True
                break
        if not replaced:
            ai_insights.append(insight)
        rec["ai_insights"] = ai_insights


def build_incidents_snapshot(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshot_records: list[dict[str, Any]] = []
    for rec in incidents:
        snapshot_records.append(
            {
                # 对外 8 字段
                "incident_id": rec["incident_id"],
                "incident_type": rec["incident_type"],
                "incident_status": rec["incident_status"],
                "charger_id": rec.get("charger_id"),
                "segment_id": rec.get("segment_id"),
                "snapshot_ref": rec.get("snapshot_ref"),
                "evidence_refs": list(ev) if (ev := rec.get("evidence_refs")) else None,
                "ai_insights": [dict(x) for x in ai] if (ai := rec.get("ai_insights")) else None,
                # 内部排序字段（对外 later 删除）
                "created_at": rec.get("created_at", 0.0),
            }
        )
    return snapshot_records


def find_incident_by_id(incidents: list[dict[str, Any]], incident_id: str) -> dict[str, Any] | None:
    rec = None
    for r in incidents:
        if r.get("incident_id") == incident_id:
            rec = r
            break
    return rec


def report_blocked_incident_locked(
    incidents: list[dict[str, Any]],
    witness_by_incident: dict[str, dict[str, Any]],
    slots: dict[str, dict[str, Any]],
    charger_id: str,
    incident_type: str,
    snapshot_ref: str | None,
    evidence_refs: list[str] | None,
    now: float,
    max_incidents: int,
    ttl_resolved_low_seconds: int,
    ttl_resolved_high_seconds: int,
    low_retention_incident_types: set[str],
    iso_utc_func,
) -> str:
    if charger_id not in slots:
        raise ValueError(f"unknown charger_id: {charger_id}")
    cleanup_incidents_locked(
        incidents,
        witness_by_incident,
        now,
        max_incidents,
        ttl_resolved_low_seconds,
        ttl_resolved_high_seconds,
        low_retention_incident_types,
    )
    incident_id = f"inc_{uuid.uuid4().hex[:12]}"
    created_at = time.time()
    resolved_snapshot_ref = snapshot_ref if snapshot_ref else iso_utc_func(created_at)
    rec = {
        "incident_id": incident_id,
        "incident_type": incident_type,
        "incident_status": "OPEN",
        "charger_id": charger_id,
        "segment_id": None,
        "snapshot_ref": resolved_snapshot_ref,
        "evidence_refs": _normalize_evidence_refs(evidence_refs),
        "ai_insights": [],
        "created_at": created_at,
        "status_updated_at": created_at,
    }
    incidents.append(rec)
    return incident_id
