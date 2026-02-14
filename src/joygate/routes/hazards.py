from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

# 系统正式封控状态（与 FIELD_REGISTRY §3 hazard_status 一致；BLOCKED/CLEAR 仅用于 segment_respond observation）
ALLOWED_HAZARD_STATUSES = {"OPEN", "SOFT_BLOCKED", "HARD_BLOCKED"}


class HazardItemOut(BaseModel):
    segment_id: str
    hazard_status: str
    obstacle_type: str | None
    evidence_refs: list[str] | None
    updated_at: str


class HazardsListOut(BaseModel):
    hazards: list[HazardItemOut]


@router.get("/v1/hazards", response_model=HazardsListOut)
def v1_hazards_list(request: Request):
    """GET /v1/hazards；严格符合 FIELD_REGISTRY HazardsList。"""
    store = request.state.store
    items = store.list_hazards()
    filtered: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        st = item.get("hazard_status")
        if st not in ALLOWED_HAZARD_STATUSES:
            raise HTTPException(status_code=500, detail="invalid hazard_status from store")
        seg = item.get("segment_id")
        if not isinstance(seg, str) or not (seg or "").strip():
            continue
        up = item.get("updated_at")
        if not isinstance(up, str) or not (up or "").strip():
            continue
        filtered.append(item)
    return {"hazards": filtered}
