# M16 信誉/计分只读接口；FIELD_REGISTRY §6) 6) M16 只读 API
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
MAX_JOYKEY_LEN = 64
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


def _norm_joykey(raw: str | None) -> str:
    if raw is None or not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="invalid joykey")
    s = raw.strip()
    if not s or len(s) > MAX_JOYKEY_LEN:
        raise HTTPException(status_code=400, detail="invalid joykey")
    return s


@router.get("/v1/reputation")
def v1_reputation_get(request: Request, joykey: str | None = None):
    """GET /v1/reputation?joykey=xxx；返回单机器人画像。无该 joykey 返回 404。"""
    if joykey is None or (isinstance(joykey, str) and not joykey.strip()):
        raise HTTPException(status_code=400, detail="joykey required")
    jk = _norm_joykey(joykey)
    store = request.state.store
    rep = store.get_reputation(jk)
    if rep is None:
        raise HTTPException(status_code=404, detail="joykey not found")
    return rep


@router.get("/v1/score_events")
def v1_score_events_list(request: Request, limit: int | None = None):
    """GET /v1/score_events?limit=100；计分事件列表，按时间倒序。"""
    if limit is None:
        limit = DEFAULT_LIMIT
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid limit")
    if limit < 0 or limit > MAX_LIMIT:
        limit = min(MAX_LIMIT, max(0, limit))
    store = request.state.store
    events = store.get_score_events(limit=limit)
    return {"score_events": events}


@router.get("/v1/vendor_scores")
def v1_vendor_scores_list(request: Request, fleet_id: str | None = None):
    """GET /v1/vendor_scores?fleet_id=xxx；厂商分列表，fleet_id 可选过滤。"""
    store = request.state.store
    items = store.get_vendor_scores(fleet_id=fleet_id)
    return {"vendor_scores": items}
