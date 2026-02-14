"""
M11 审计账本：GET /v1/audit/ledger；POST /v1/audit/sidecar_safety_event（demo 注入）。
audit_status 仅来自 store，不在路由写死。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# 与 FIELD_REGISTRY oem_result / safety_observed_by 一致
ALLOWED_OEM_RESULT = {"ACCEPTED", "IGNORED", "REJECTED", "SAFETY_FALLBACK", "FAILED"}
ALLOWED_SAFETY_OBSERVED_BY = {"TELEMETRY", "TIMEOUT", "OEM_CALLBACK"}

router = APIRouter()


class SidecarSafetyEventIn(BaseModel):
    suggestion_id: Optional[str] = None
    joykey: Optional[str] = None
    fleet_id: Optional[str] = None
    oem_result: str
    fallback_reason: Optional[str] = None
    observed_by: str
    observed_at: Any


@router.get("/v1/audit/ledger")
def v1_audit_ledger(request: Request):
    """GET /v1/audit/ledger；返回 audit_status / decisions / sidecar_safety_events，均来自 store。"""
    store = request.state.store
    return store.get_audit_ledger()


@router.post("/v1/audit/sidecar_safety_event", status_code=204)
def v1_audit_sidecar_safety_event(req: SidecarSafetyEventIn, request: Request):
    """POST /v1/audit/sidecar_safety_event；demo-only 注入，校验 oem_result / observed_by / observed_at。"""
    if req.oem_result not in ALLOWED_OEM_RESULT:
        raise HTTPException(status_code=400, detail=f"invalid oem_result: {req.oem_result!r}")
    if req.observed_by not in ALLOWED_SAFETY_OBSERVED_BY:
        raise HTTPException(status_code=400, detail=f"invalid observed_by: {req.observed_by!r}")
    raw = req.observed_at
    if isinstance(raw, bool):
        raise HTTPException(status_code=400, detail="observed_at must be number (epoch seconds)")
    if type(raw) not in (int, float):
        raise HTTPException(status_code=400, detail="observed_at must be number (epoch seconds)")
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid observed_at")
    store = request.state.store
    payload = {
        "suggestion_id": req.suggestion_id,
        "joykey": req.joykey,
        "fleet_id": req.fleet_id,
        "oem_result": req.oem_result,
        "fallback_reason": req.fallback_reason,
        "observed_by": req.observed_by,
        "observed_at": ts,
    }
    store.append_sidecar_safety_event(payload)
    return None
