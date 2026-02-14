from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from joygate.routes.incidents import (
    _dispatch_webhook_outbox,
    _validate_evidence_refs_route,
    _validate_optional_str,
    _validate_required_str,
)

router = APIRouter()

ALLOWED_CHARGER_STATES = {"FREE", "OCCUPIED", "UNKNOWN_OCCUPANCY"}
ALLOWED_HAZARD_STATUSES = {"BLOCKED", "CLEAR"}
ALLOWED_SEGMENT_STATES = {"PASSABLE", "BLOCKED", "UNKNOWN"}


class WitnessResponseIn(BaseModel):
    """POST /v1/witness/respond 请求体，严格对齐 FIELD_REGISTRY WitnessResponseRequest。"""
    incident_id: str
    charger_id: str
    charger_state: str  # enum: FREE / OCCUPIED / UNKNOWN_OCCUPANCY
    obstacle_type: Optional[str] = None
    evidence_refs: Optional[list[str]] = None
    points_event_id: Optional[str] = None


@router.post("/v1/witness/respond")
def v1_witness_respond(req: WitnessResponseIn, request: Request, background_tasks: BackgroundTasks):
    """M8 witness 桩占用投票；witness 身份来自 X-JoyKey；成功 204 No Content。"""
    joykey_raw = request.headers.get("X-JoyKey")
    if joykey_raw is None or (isinstance(joykey_raw, str) and not joykey_raw.strip()):
        raise HTTPException(status_code=400, detail="missing X-JoyKey")
    witness_joykey = _validate_required_str(joykey_raw, "witness_joykey")
    incident_id = _validate_required_str(req.incident_id, "incident_id")
    charger_id = _validate_required_str(req.charger_id, "charger_id")
    charger_state = _validate_required_str(req.charger_state, "charger_state")
    if charger_state not in ALLOWED_CHARGER_STATES:
        raise HTTPException(status_code=400, detail="invalid charger_state")
    obstacle_type = _validate_optional_str(req.obstacle_type, "obstacle_type")
    evidence_refs = _validate_evidence_refs_route(req.evidence_refs, "evidence_refs")
    points_event_id = _validate_optional_str(req.points_event_id, "points_event_id")
    store = request.state.store
    try:
        store.witness_respond(
            witness_joykey=witness_joykey,
            incident_id=incident_id,
            charger_id=charger_id,
            charger_state=charger_state,
            obstacle_type=obstacle_type,
            evidence_refs=evidence_refs,
            points_event_id=points_event_id,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="witness not allowed")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown incident_id: {incident_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return Response(status_code=204)


class SegmentWitnessResponseIn(BaseModel):
    """POST /v1/witness/segment_respond 请求体，对齐 FIELD_REGISTRY；segment_state 与 hazard_status 二选一；points_event_id 必填（幂等去重）。"""
    segment_id: str
    segment_state: Optional[str] = None  # PASSABLE | BLOCKED | UNKNOWN（M14.3）
    hazard_status: Optional[str] = None   # 兼容：BLOCKED | CLEAR
    obstacle_type: Optional[str] = None
    evidence_refs: Optional[list[str]] = None
    points_event_id: Optional[str] = None  # 路由层强制必填，缺失/空→400


@router.post("/v1/witness/segment_respond")
def v1_witness_segment_respond(req: SegmentWitnessResponseIn, request: Request, background_tasks: BackgroundTasks):
    """M9/M14.3 Segment witness；witness 身份来自 X-JoyKey；segment_state 或 hazard_status；成功 204。"""
    joykey_raw = request.headers.get("X-JoyKey")
    if joykey_raw is None or (isinstance(joykey_raw, str) and not joykey_raw.strip()):
        raise HTTPException(status_code=400, detail="missing X-JoyKey")
    witness_joykey = _validate_required_str(joykey_raw, "witness_joykey")
    segment_id = _validate_required_str(req.segment_id, "segment_id")
    obstacle_type = _validate_optional_str(req.obstacle_type, "obstacle_type")
    evidence_refs = _validate_evidence_refs_route(req.evidence_refs, "evidence_refs")
    if req.points_event_id is None or not isinstance(req.points_event_id, str):
        raise HTTPException(status_code=400, detail="invalid points_event_id")
    points_event_id = _validate_required_str(req.points_event_id, "points_event_id")

    use_segment_state = req.segment_state is not None and (req.segment_state or "").strip()
    if use_segment_state:
        segment_state = _validate_required_str(req.segment_state, "segment_state")
        if segment_state not in ALLOWED_SEGMENT_STATES:
            raise HTTPException(status_code=400, detail="invalid segment_state")
        store = request.state.store
        try:
            store.record_segment_witness(
                segment_id=segment_id,
                segment_state=segment_state,
                witness_joykey=witness_joykey,
                points_event_id=points_event_id,
                evidence_refs=evidence_refs,
                obstacle_type=obstacle_type,
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="witness not allowed")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        if req.hazard_status is None or not isinstance(req.hazard_status, str) or not (req.hazard_status or "").strip():
            raise HTTPException(status_code=400, detail="invalid hazard_status")
        hazard_status = _validate_required_str(req.hazard_status, "hazard_status")
        if hazard_status not in ALLOWED_HAZARD_STATUSES:
            raise HTTPException(status_code=400, detail="invalid hazard_status")
        store = request.state.store
        try:
            store.segment_witness_respond(
                witness_joykey=witness_joykey,
                segment_id=segment_id,
                hazard_status=hazard_status,
                obstacle_type=obstacle_type,
                evidence_refs=evidence_refs,
                points_event_id=points_event_id,
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="witness not allowed")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return Response(status_code=204)
