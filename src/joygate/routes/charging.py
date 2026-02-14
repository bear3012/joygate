from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()
MAX_JOYKEY_LEN = 128
MAX_RESOURCE_TYPE_LEN = 32
MAX_RESOURCE_ID_LEN = 64
MAX_ACTION_LEN = 16
MAX_HOLD_ID_LEN = 64
MAX_CHARGER_ID_LEN = 64
MAX_METER_SESSION_ID_LEN = 64
MAX_EVENT_OCCURRED_AT_LEN = 64


class ReserveRequestIn(BaseModel):
    resource_type: str
    resource_id: str
    joykey: str
    action: str


class OracleEventIn(BaseModel):
    hold_id: str
    charger_id: str
    meter_session_id: str
    event_occurred_at: str


@router.post("/v1/reserve")
def v1_reserve(req: ReserveRequestIn, request: Request):
    if not isinstance(req.action, str):
        raise HTTPException(status_code=400, detail="invalid action")
    action_s = req.action.strip()
    if not action_s or req.action != action_s or len(action_s) > MAX_ACTION_LEN or action_s != "HOLD":
        raise HTTPException(status_code=400, detail="invalid action")
    if not isinstance(req.joykey, str):
        raise HTTPException(status_code=400, detail="invalid joykey")
    s = req.joykey.strip()
    if not s or req.joykey != s or len(s) > MAX_JOYKEY_LEN:
        raise HTTPException(status_code=400, detail="invalid joykey")
    if not isinstance(req.resource_type, str):
        raise HTTPException(status_code=400, detail="invalid resource_type")
    rt = req.resource_type.strip()
    if not rt or req.resource_type != rt or len(rt) > MAX_RESOURCE_TYPE_LEN:
        raise HTTPException(status_code=400, detail="invalid resource_type")
    if not isinstance(req.resource_id, str):
        raise HTTPException(status_code=400, detail="invalid resource_id")
    rid = req.resource_id.strip()
    if not rid or req.resource_id != rid or len(rid) > MAX_RESOURCE_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid resource_id")

    store = request.state.store
    try:
        status_code, payload = store.reserve(rt, rid, s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    return payload


@router.post("/v1/oracle/start_charging")
def oracle_start(req: OracleEventIn, request: Request):
    if not isinstance(req.hold_id, str):
        raise HTTPException(status_code=400, detail="invalid hold_id")
    s_hold_id = req.hold_id.strip()
    if not s_hold_id or req.hold_id != s_hold_id or len(s_hold_id) > MAX_HOLD_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid hold_id")
    if not isinstance(req.charger_id, str):
        raise HTTPException(status_code=400, detail="invalid charger_id")
    s_charger_id = req.charger_id.strip()
    if not s_charger_id or req.charger_id != s_charger_id or len(s_charger_id) > MAX_CHARGER_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid charger_id")
    if not isinstance(req.meter_session_id, str):
        raise HTTPException(status_code=400, detail="invalid meter_session_id")
    s_meter = req.meter_session_id.strip()
    if not s_meter or req.meter_session_id != s_meter or len(s_meter) > MAX_METER_SESSION_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid meter_session_id")
    if not isinstance(req.event_occurred_at, str):
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    s_occurred = req.event_occurred_at.strip()
    if not s_occurred or req.event_occurred_at != s_occurred or len(s_occurred) > MAX_EVENT_OCCURRED_AT_LEN:
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    store = request.state.store
    store.start_charging(s_hold_id, s_charger_id)
    return {"ok": True, "truth_event": "START_CHARGING"}


@router.post("/v1/oracle/stop_charging")
def oracle_stop(req: OracleEventIn, request: Request):
    if not isinstance(req.hold_id, str):
        raise HTTPException(status_code=400, detail="invalid hold_id")
    s_hold_id = req.hold_id.strip()
    if not s_hold_id or req.hold_id != s_hold_id or len(s_hold_id) > MAX_HOLD_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid hold_id")
    if not isinstance(req.charger_id, str):
        raise HTTPException(status_code=400, detail="invalid charger_id")
    s_charger_id = req.charger_id.strip()
    if not s_charger_id or req.charger_id != s_charger_id or len(s_charger_id) > MAX_CHARGER_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid charger_id")
    if not isinstance(req.meter_session_id, str):
        raise HTTPException(status_code=400, detail="invalid meter_session_id")
    s_meter = req.meter_session_id.strip()
    if not s_meter or req.meter_session_id != s_meter or len(s_meter) > MAX_METER_SESSION_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid meter_session_id")
    if not isinstance(req.event_occurred_at, str):
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    s_occurred = req.event_occurred_at.strip()
    if not s_occurred or req.event_occurred_at != s_occurred or len(s_occurred) > MAX_EVENT_OCCURRED_AT_LEN:
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    store = request.state.store
    store.stop_charging(s_hold_id, s_charger_id)
    return {"ok": True, "truth_event": "STOP_CHARGING"}


@router.get("/v1/snapshot")
def v1_snapshot(request: Request):
    """返回当前 chargers / holds 快照，字段严格符合 FIELD_REGISTRY SnapshotOK。"""
    store = request.state.store
    return store.snapshot()


@router.get("/v1/policy")
def v1_policy(request: Request):
    """M14.1：返回制度参数（store.get_policy()），FIELD_REGISTRY §4 Policy Config。"""
    store = request.state.store
    return store.get_policy()
