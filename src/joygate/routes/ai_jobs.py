from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from joygate.ai_jobs import DISPATCH_REASON_CODES
from joygate.routes.incidents import _dispatch_webhook_outbox
from joygate.routes._input_norm import norm_evidence_refs as norm_evidence_refs_strict

router = APIRouter()

# M13.2：model_tier 枚举（与 FIELD_REGISTRY ai_model_tier 一致）
AI_MODEL_TIERS = {"FLASH", "PRO"}
# 入口限长（与 store 一致，ID 类 64）
MAX_INCIDENT_ID_LEN = 64
MAX_HOLD_ID_LEN = 64
MAX_AUDIENCE_LEN = 64
MAX_OBSTACLE_TYPE_LEN = 64
MAX_SNAPSHOT_REF_LEN = 64
MAX_EVIDENCE_REF_LEN = 120
MAX_EVIDENCE_REFS = 5
# audience / obstacle_type 枚举（FIELD_REGISTRY §3）
ALLOWED_AUDIENCE = {"USER", "ADMIN", "SYSTEM"}
ALLOWED_OBSTACLE_TYPES = {
    "BLOCKED_BY_CHARGER", "QUEUE_DELAY", "UNKNOWN", "ICE_VEHICLE", "CHARGER_FAULT", "CONSTRUCTION",
}


def _validate_model_tier(model_tier: str | None) -> str | None:
    """若提供则必须是 FLASH 或 PRO，否则 raise HTTPException 400。"""
    if model_tier is None or (isinstance(model_tier, str) and not model_tier.strip()):
        return None
    s = model_tier.strip()
    if s not in AI_MODEL_TIERS:
        raise HTTPException(status_code=400, detail="invalid model_tier")
    return s


def _norm_required_str(field: str, value: str | None, max_len: int) -> str:
    """strip 后非空且长度≤max_len，禁止首尾空白；否则 400 invalid <field>。"""
    if value is None or not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    s = value.strip()
    if value != s or not s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    return s


def _norm_optional_str(field: str, value: str | None, max_len: int) -> str | None:
    """可选：strip 后空则 None；否则长度≤max_len、禁止前后空白；否则 400 invalid <field>。"""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if value != s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    return s


class AiJobsVisionAuditIn(BaseModel):
    incident_id: str
    model_tier: str | None = None


class VisionAuditIn(BaseModel):
    """FIELD_REGISTRY /v1/ai/vision_audit 输入。"""
    snapshot_ref: str | None = None
    evidence_refs: list[str] | None = None
    incident_id: str | None = None
    model_tier: str | None = None


class AiJobsTickIn(BaseModel):
    max_jobs: int


class DispatchExplainIn(BaseModel):
    """FIELD_REGISTRY /v1/ai/dispatch_explain 输入。"""
    hold_id: str
    obstacle_type: str | None = None
    audience: str
    dispatch_reason_codes: list[str]
    context_ref: str | None = None
    model_tier: str | None = None


class PolicySuggestIn(BaseModel):
    """FIELD_REGISTRY /v1/ai/policy_suggest 输入；evidence_only，无 prompt/text/instruction。"""
    incident_id: str | None = None
    context_ref: str | None = None
    model_tier: str | None = None


@router.post("/v1/ai/dispatch_explain", status_code=202)
def v1_ai_dispatch_explain(req: DispatchExplainIn, request: Request, background_tasks: BackgroundTasks):
    """M13.0: dispatch_explain 入队，校验 dispatch_reason_codes 在枚举内，context_ref 同 policy_suggest，返回 202。M13.2: 入口 strip/64。"""
    context_ref_norm = _norm_optional_str("context_ref", req.context_ref, CONTEXT_REF_MAX_LEN)
    _validate_context_ref(context_ref_norm)
    model_tier = _validate_model_tier(req.model_tier)
    if model_tier is None:
        model_tier = "FLASH"
    hold_id = _norm_required_str("hold_id", req.hold_id, MAX_HOLD_ID_LEN)
    audience_raw = _norm_required_str("audience", req.audience, MAX_AUDIENCE_LEN)
    if audience_raw not in ALLOWED_AUDIENCE:
        raise HTTPException(status_code=400, detail="invalid audience")
    obstacle_type: str | None = _norm_optional_str("obstacle_type", req.obstacle_type, MAX_OBSTACLE_TYPE_LEN)
    if obstacle_type is not None and obstacle_type not in ALLOWED_OBSTACLE_TYPES:
        raise HTTPException(status_code=400, detail="invalid obstacle_type")
    if not (req.dispatch_reason_codes and isinstance(req.dispatch_reason_codes, list)):
        raise HTTPException(status_code=400, detail="dispatch_reason_codes required and must be non-empty list")
    for code in req.dispatch_reason_codes:
        if not isinstance(code, str) or code not in DISPATCH_REASON_CODES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid dispatch_reason_code: {code!r}; allowed: {sorted(DISPATCH_REASON_CODES)}",
            )
    store = request.state.store
    try:
        job = store.create_dispatch_explain_job(
            hold_id=hold_id,
            obstacle_type=obstacle_type,
            audience=audience_raw,
            dispatch_reason_codes=req.dispatch_reason_codes,
            context_ref=context_ref_norm,
            model_tier=model_tier,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return {
        "ai_report_id": job.get("ai_report_id"),
        "status": job.get("ai_job_status"),
    }


CONTEXT_REF_MAX_LEN = 64

# 敏感模式（命中任一则 400）；64 位 hex 不作为敏感
_SENSITIVE_SUBSTRINGS = [
    "-----BEGIN",
    "PRIVATE KEY",
    "ssh-rsa",
    "AKIA",
    "ghp_",
    "xoxb-",
    "AIza",
    "sk-",
]
_SENSITIVE_SUBSTRINGS_CI = ["bearer ", "authorization:"]


def _validate_context_ref(context_ref: str | None) -> None:
    """context_ref 长度≤64、禁止控制字符、禁止敏感模式；违规 raise HTTPException 400。"""
    if context_ref is None or (isinstance(context_ref, str) and not context_ref.strip()):
        return
    s = context_ref.strip() if isinstance(context_ref, str) else ""
    if len(s) > CONTEXT_REF_MAX_LEN:
        raise HTTPException(status_code=400, detail="invalid context_ref")
    if any(ord(c) < 32 for c in s):
        raise HTTPException(status_code=400, detail="invalid context_ref")
    # 64 位 hex（正当 ref）不判敏感
    if len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower()):
        return
    lower = s.lower()
    for sub in _SENSITIVE_SUBSTRINGS_CI:
        if sub in lower:
            raise HTTPException(status_code=400, detail="context_ref rejected: looks sensitive; use opaque ref")
    for sub in _SENSITIVE_SUBSTRINGS:
        if sub in s:
            raise HTTPException(status_code=400, detail="context_ref rejected: looks sensitive; use opaque ref")


@router.post("/v1/ai/policy_suggest", status_code=202)
def v1_ai_policy_suggest(req: PolicySuggestIn, request: Request, background_tasks: BackgroundTasks):
    """M13.1: policy_suggest 入队；evidence_only，context_ref 入口 64；model_tier 默认 PRO。"""
    context_ref_norm = _norm_optional_str("context_ref", req.context_ref, CONTEXT_REF_MAX_LEN)
    _validate_context_ref(context_ref_norm)
    model_tier = _validate_model_tier(req.model_tier)
    if model_tier is None:
        model_tier = "PRO"
    incident_id = _norm_optional_str("incident_id", req.incident_id, MAX_INCIDENT_ID_LEN)
    store = request.state.store
    try:
        job = store.create_policy_suggest_job(
            incident_id=incident_id,
            context_ref=context_ref_norm,
            model_tier=model_tier,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return {
        "ai_report_id": job.get("ai_report_id"),
        "status": job.get("ai_job_status"),
    }


@router.post("/v1/ai/vision_audit", status_code=202)
def v1_ai_vision_audit(req: VisionAuditIn, request: Request, background_tasks: BackgroundTasks):
    """M12A-1: 视觉审计入队，仅返回 202 + ai_report_id + status，不等待 Gemini。M13.2: model_tier 可选默认 FLASH；snapshot_ref/evidence_refs 入 job；入口 strip/限长。"""
    incident_id = _norm_required_str("incident_id", req.incident_id, MAX_INCIDENT_ID_LEN)
    model_tier = _validate_model_tier(req.model_tier)
    if model_tier is None:
        model_tier = "FLASH"
    snapshot_ref = _norm_optional_str("snapshot_ref", req.snapshot_ref, MAX_SNAPSHOT_REF_LEN)
    evidence_refs = norm_evidence_refs_strict(req.evidence_refs)
    store = request.state.store
    try:
        job = store.create_vision_audit_job(
            incident_id=incident_id,
            model_tier=model_tier,
            snapshot_ref=snapshot_ref,
            evidence_refs=evidence_refs,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown incident_id: {incident_id}")
    _dispatch_webhook_outbox(store, background_tasks)
    return {
        "ai_report_id": job.get("ai_report_id"),
        "status": job.get("ai_job_status"),
    }


@router.post("/v1/ai_jobs/vision_audit")
def v1_ai_jobs_vision_audit(req: AiJobsVisionAuditIn, request: Request, background_tasks: BackgroundTasks):
    """M9.1: 创建视觉审计 job，返回 {ai_job_id, ai_job_type, ai_job_status}。M13.2: 可选 model_tier，向后兼容不传。"""
    incident_id = _norm_required_str("incident_id", req.incident_id, MAX_INCIDENT_ID_LEN)
    model_tier = _validate_model_tier(req.model_tier)
    if model_tier is None:
        model_tier = "FLASH"
    store = request.state.store
    try:
        job = store.create_vision_audit_job(
            incident_id=incident_id,
            model_tier=model_tier,
            snapshot_ref=None,
            evidence_refs=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown incident_id: {incident_id}")
    _dispatch_webhook_outbox(store, background_tasks)
    return {
        "ai_job_id": job.get("ai_job_id"),
        "ai_job_type": job.get("ai_job_type"),
        "ai_job_status": job.get("ai_job_status"),
    }


@router.post("/v1/ai_jobs/tick")
def v1_ai_jobs_tick(req: AiJobsTickIn, request: Request, background_tasks: BackgroundTasks):
    """M9.1: 推进 AI Jobs（demo 驱动器）。"""
    store = request.state.store
    result = store.tick_ai_jobs(req.max_jobs)
    _dispatch_webhook_outbox(store, background_tasks)
    return result


@router.get("/v1/ai_jobs")
def v1_ai_jobs_list(request: Request):
    """M9.1: 查询 AI Jobs 列表。"""
    store = request.state.store
    return {"jobs": store.list_ai_jobs()}
