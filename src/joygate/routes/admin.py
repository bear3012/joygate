# M13.1：admin 仅记账接口，不改权威状态
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ApplyPolicyIn(BaseModel):
    """FIELD_REGISTRY ApplyPolicyRequest。"""
    ai_report_id: str
    confirm: bool


POLICY_SUGGEST_TYPE = "POLICY_SUGGEST"


@router.post("/v1/admin/apply_policy_suggestion", status_code=202)
def v1_admin_apply_policy_suggestion(req: ApplyPolicyIn, request: Request):
    """M13.1：校验 ai_report_id 归属与状态后写 POLICY_APPLIED，不改 incident/hazard/hold。"""
    if req.confirm is not True:
        raise HTTPException(status_code=400, detail="confirm required (true)")
    ai_report_id = (req.ai_report_id or "").strip()
    store = request.state.store
    job = store.get_ai_job_by_report_id(ai_report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ai_report_id not found")
    if job.get("ai_job_type") != POLICY_SUGGEST_TYPE:
        raise HTTPException(status_code=400, detail="ai_report_id is not a POLICY_SUGGEST report")
    if job.get("ai_job_status") != "COMPLETED":
        raise HTTPException(status_code=409, detail="policy_suggest not completed")
    if not store.ledger_has_policy_suggested(ai_report_id):
        raise HTTPException(status_code=409, detail="missing POLICY_SUGGESTED decision")
    payload = store.apply_policy_suggestion_ledger_only(ai_report_id)
    return payload
