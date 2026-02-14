from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any

AI_JOB_TYPE_VISION_AUDIT = "VISION_AUDIT"
AI_JOB_TYPE_DISPATCH_EXPLAIN = "DISPATCH_EXPLAIN"
AI_JOB_TYPE_POLICY_SUGGEST = "POLICY_SUGGEST"
# M13.0 dispatch_reason_code 推荐值集合（与 FIELD_REGISTRY 一致）
DISPATCH_REASON_CODES = {
    "QUOTA_EXCEEDED",
    "CHARGER_BUSY",
    "INCIDENT_REPORTED",
    "WITNESS_CONFIRMED",
    "VISION_CONFIRMED",
    "SEGMENT_HAZARD_SIGNAL",
    "SEGMENT_FRESHNESS_SIGNAL",
    "BUDGET_SKIPPED",
    "SAFETY_FALLBACK",
    "POLICY_RULE",
    "OTHER",
}
# 幂等：同一 incident 在 terminal 后 dedup_seconds 内不新建 job（internal，环境变量可覆盖）
_dedup_raw = os.getenv("JOYGATE_AI_JOB_DEDUP_SECONDS", "60")
try:
    JOYGATE_AI_JOB_DEDUP_SECONDS = max(0, int(_dedup_raw))
except (ValueError, TypeError):
    JOYGATE_AI_JOB_DEDUP_SECONDS = 60
# 防卡死：IN_PROGRESS job 超时后重新变为 ACCEPTED（internal，环境变量可覆盖；最小 1）
_lease_raw = os.getenv("JOYGATE_AI_JOB_LEASE_SECONDS", "30")
try:
    JOYGATE_AI_JOB_LEASE_SECONDS = max(1, int(_lease_raw))
except (ValueError, TypeError):
    JOYGATE_AI_JOB_LEASE_SECONDS = 30
ALLOWED_AI_JOB_STATUS = {"ACCEPTED", "IN_PROGRESS", "COMPLETED", "FAILED"}
ACTIVE_AI_JOB_STATUS = {"ACCEPTED", "IN_PROGRESS"}
TERMINAL_AI_JOB_STATUS = {"COMPLETED", "FAILED"}


def cleanup_ai_jobs_locked(
    ai_jobs: dict,
    ai_job_queue: list,
    active_index: dict,
    now: float,
    retention_seconds: int,
) -> None:
    if retention_seconds <= 0:
        return
    to_delete: list[str] = []
    for job_id, job in ai_jobs.items():
        if not isinstance(job, dict):
            continue
        status = job.get("ai_job_status")
        if status not in TERMINAL_AI_JOB_STATUS:
            continue
        completed_at = job.get("completed_at")
        base_ts = completed_at if completed_at is not None else job.get("created_at")
        if base_ts is None:
            continue
        if (now - float(base_ts)) > retention_seconds:
            to_delete.append(job_id)
    if not to_delete:
        return
    delete_set = set(to_delete)
    ai_job_queue[:] = [jid for jid in ai_job_queue if jid not in delete_set]
    for job_id in to_delete:
        job = ai_jobs.get(job_id)
        if isinstance(job, dict):
            incident_id = job.get("incident_id")
            if incident_id and active_index.get(incident_id) == job_id:
                active_index.pop(incident_id, None)
        ai_jobs.pop(job_id, None)


def create_vision_audit_job_locked(
    incidents: list[dict],
    ai_jobs: dict,
    ai_job_queue: list,
    active_index: dict,
    incident_id: str,
    now: float,
    render_snapshot: dict | None = None,
    model_tier: str | None = None,
    snapshot_ref: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict:
    """创建视觉审计 job；render_snapshot 为 internal 字段存于 job，不暴露给 list_ai_jobs。M13.2: model_tier/snapshot_ref/evidence_refs 存 job 用于审计。"""

    def _public_job_view(job: dict) -> dict:
        return {
            "ai_job_id": job.get("ai_job_id"),
            "ai_job_type": job.get("ai_job_type"),
            "ai_job_status": job.get("ai_job_status"),
            "ai_report_id": job.get("ai_report_id"),
        }

    rec = None
    for r in incidents:
        if r.get("incident_id") == incident_id:
            rec = r
            break
    if rec is None:
        raise KeyError(f"incident not found: {incident_id}")

    active_job_id = active_index.get(incident_id)
    if active_job_id:
        job = ai_jobs.get(active_job_id)
        if isinstance(job, dict) and job.get("ai_job_status") in ACTIVE_AI_JOB_STATUS:
            return _public_job_view(job)
        active_index.pop(incident_id, None)

    # terminal dedupe：只对 terminal 状态 job；复用窗口基准 base_ts = completed_at ?? created_at
    dedup_seconds = JOYGATE_AI_JOB_DEDUP_SECONDS
    if dedup_seconds > 0:
        same_incident_terminal = [
            (jid, j) for jid, j in ai_jobs.items()
            if isinstance(j, dict)
            and j.get("incident_id") == incident_id
            and j.get("ai_job_status") in TERMINAL_AI_JOB_STATUS
        ]
        if same_incident_terminal:
            def _base_ts(j: dict) -> float:
                completed_at = j.get("completed_at")
                created_at = j.get("created_at")
                return float(completed_at if completed_at is not None else created_at or 0)
            latest = max(same_incident_terminal, key=lambda x: _base_ts(x[1]))
            jid, j = latest
            base_ts = _base_ts(j)
            if base_ts > 0 and (now - base_ts) <= dedup_seconds:
                return _public_job_view(j)

    ai_job_id = f"job_{uuid.uuid4().hex[:12]}"
    ai_report_id = f"airpt_{uuid.uuid4().hex[:12]}"
    job = {
        "ai_job_id": ai_job_id,
        "ai_job_type": AI_JOB_TYPE_VISION_AUDIT,
        "ai_job_status": "ACCEPTED",
        "ai_report_id": ai_report_id,
        "incident_id": incident_id,
        "created_at": now,
    }
    if model_tier is not None:
        job["model_tier"] = model_tier
    if snapshot_ref is not None:
        job["snapshot_ref"] = snapshot_ref
    if evidence_refs is not None and len(evidence_refs) > 0:
        job["evidence_refs"] = list(evidence_refs)
    if render_snapshot is not None:
        job["render_snapshot"] = dict(render_snapshot)
    ai_jobs[ai_job_id] = job
    ai_job_queue.append(ai_job_id)
    active_index[incident_id] = ai_job_id
    return _public_job_view(job)


def create_dispatch_explain_job_locked(
    ai_jobs: dict,
    ai_job_queue: list,
    hold_id: str,
    obstacle_type: str | None,
    audience: str,
    dispatch_reason_codes: list[str],
    context_ref: str | None,
    now: float,
    model_tier: str | None = None,
) -> dict:
    """M13.0：创建 dispatch_explain job；无 incident 维度的 dedup，直接入队。M13.2: model_tier 存 job。"""
    ai_job_id = f"job_{uuid.uuid4().hex[:12]}"
    ai_report_id = f"airpt_{uuid.uuid4().hex[:12]}"
    job = {
        "ai_job_id": ai_job_id,
        "ai_job_type": AI_JOB_TYPE_DISPATCH_EXPLAIN,
        "ai_job_status": "ACCEPTED",
        "ai_report_id": ai_report_id,
        "hold_id": hold_id,
        "obstacle_type": obstacle_type,
        "audience": audience,
        "dispatch_reason_codes": list(dispatch_reason_codes) if dispatch_reason_codes else [],
        "context_ref": context_ref,
        "created_at": now,
    }
    if model_tier is not None:
        job["model_tier"] = model_tier
    ai_jobs[ai_job_id] = job
    ai_job_queue.append(ai_job_id)
    return {
        "ai_job_id": job.get("ai_job_id"),
        "ai_job_type": job.get("ai_job_type"),
        "ai_job_status": job.get("ai_job_status"),
        "ai_report_id": job.get("ai_report_id"),
    }


def create_policy_suggest_job_locked(
    ai_jobs: dict,
    ai_job_queue: list,
    incident_id: str | None,
    context_ref: str | None,
    now: float,
    model_tier: str | None = None,
) -> dict:
    """M13.1：创建 policy_suggest job；只存 context_ref_sha256（full 64 hex），不存原文。M13.2: model_tier 存 job。"""
    ai_job_id = f"job_{uuid.uuid4().hex[:12]}"
    ai_report_id = f"airpt_{uuid.uuid4().hex[:12]}"
    context_ref_sha256: str | None = None
    if isinstance(context_ref, str) and context_ref.strip():
        context_ref_sha256 = hashlib.sha256(context_ref.strip().encode("utf-8")).hexdigest()
    job = {
        "ai_job_id": ai_job_id,
        "ai_job_type": AI_JOB_TYPE_POLICY_SUGGEST,
        "ai_job_status": "ACCEPTED",
        "ai_report_id": ai_report_id,
        "incident_id": incident_id,
        "context_ref_sha256": context_ref_sha256,
        "created_at": now,
    }
    if model_tier is not None:
        job["model_tier"] = model_tier
    ai_jobs[ai_job_id] = job
    ai_job_queue.append(ai_job_id)
    return {
        "ai_job_id": job.get("ai_job_id"),
        "ai_job_type": job.get("ai_job_type"),
        "ai_job_status": job.get("ai_job_status"),
        "ai_report_id": job.get("ai_report_id"),
    }


def tick_ai_jobs_locked(
    incidents: list[dict],
    ai_jobs: dict,
    ai_job_queue: list,
    active_index: dict,
    max_jobs: int,
    now: float,
) -> tuple[int, list[dict]]:
    """
    两段式：仅锁内收集待处理任务，不执行 I/O。
    返回 (processed, tasks)，每个 task 为 dict：job_id, incident_id, ai_report_id, lease_until, render_snapshot（拷贝）, incident_rec（拷贝）, use_budget。
    """
    # lease 机制：IN_PROGRESS 超时则改回 ACCEPTED 并重新入队，防卡死
    queue_set = set(ai_job_queue)
    for job_id, job in list(ai_jobs.items()):
        if not isinstance(job, dict):
            continue
        if job.get("ai_job_status") != "IN_PROGRESS":
            continue
        lease_until = job.get("lease_until")
        if lease_until is None or float(lease_until) >= now:
            continue
        job["ai_job_status"] = "ACCEPTED"
        job.pop("lease_until", None)
        if job_id not in queue_set:
            ai_job_queue.append(job_id)
            queue_set.add(job_id)

    limit = max_jobs if max_jobs > 0 else 0
    processed = 0
    tasks: list[dict] = []
    while processed < limit and ai_job_queue:
        ai_job_id = ai_job_queue.pop(0)
        job = ai_jobs.get(ai_job_id)
        if not isinstance(job, dict):
            continue
        status = job.get("ai_job_status")
        if status != "ACCEPTED":
            continue
        processed += 1
        job["ai_job_status"] = "IN_PROGRESS"
        job["lease_until"] = now + JOYGATE_AI_JOB_LEASE_SECONDS

        ai_job_type = job.get("ai_job_type")
        ai_report_id = job.get("ai_report_id")
        if ai_job_type == AI_JOB_TYPE_DISPATCH_EXPLAIN:
            tasks.append({
                "job_id": ai_job_id,
                "incident_id": None,
                "ai_report_id": ai_report_id,
                "ai_job_type": AI_JOB_TYPE_DISPATCH_EXPLAIN,
                "lease_until": job.get("lease_until"),
                "hold_id": job.get("hold_id"),
                "obstacle_type": job.get("obstacle_type"),
                "audience": job.get("audience"),
                "dispatch_reason_codes": list(job.get("dispatch_reason_codes") or []),
                "context_ref": job.get("context_ref"),
                "use_budget": False,
            })
            continue

        if ai_job_type == AI_JOB_TYPE_POLICY_SUGGEST:
            tasks.append({
                "job_id": ai_job_id,
                "incident_id": job.get("incident_id"),
                "ai_report_id": ai_report_id,
                "ai_job_type": AI_JOB_TYPE_POLICY_SUGGEST,
                "lease_until": job.get("lease_until"),
                "context_ref_sha256": job.get("context_ref_sha256"),
                "use_budget": False,
            })
            continue

        incident_id = job.get("incident_id")
        rec = None
        for r in incidents:
            if r.get("incident_id") == incident_id:
                rec = r
                break
        if rec is None:
            job["ai_job_status"] = "FAILED"
            job.pop("lease_until", None)
            job["completed_at"] = now
            if incident_id:
                active_index.pop(incident_id, None)
            continue

        render_snapshot = job.get("render_snapshot")
        if not isinstance(render_snapshot, dict):
            render_snapshot = {}
        ev_refs = rec.get("evidence_refs")
        evidence_refs = list(ev_refs)[:5] if isinstance(ev_refs, list) else []
        incident_rec = {
            "incident_id": rec.get("incident_id"),
            "incident_type": rec.get("incident_type"),
            "incident_status": rec.get("incident_status"),
            "charger_id": rec.get("charger_id"),
            "segment_id": rec.get("segment_id"),
            "snapshot_ref": rec.get("snapshot_ref"),
            "evidence_refs": evidence_refs,
        }
        tasks.append({
            "job_id": ai_job_id,
            "incident_id": incident_id,
            "ai_report_id": ai_report_id,
            "ai_job_type": job.get("ai_job_type"),
            "lease_until": job.get("lease_until"),
            "render_snapshot": dict(render_snapshot),
            "incident_rec": incident_rec,
            "use_budget": True,
        })
    return (processed, tasks)


def list_ai_jobs_locked(ai_jobs: dict) -> list[dict]:
    """M13.2: 输出含 model_tier 用于审计。"""
    jobs: list[dict[str, Any]] = []
    for job in ai_jobs.values():
        if not isinstance(job, dict):
            continue
        item = {
            "ai_job_id": job.get("ai_job_id"),
            "ai_job_type": job.get("ai_job_type"),
            "ai_job_status": job.get("ai_job_status"),
            "incident_id": job.get("incident_id"),
        }
        mt = job.get("model_tier")
        if mt is not None:
            item["model_tier"] = mt
        jobs.append(item)
    jobs.sort(key=lambda x: x.get("ai_job_id") or "")
    return jobs
