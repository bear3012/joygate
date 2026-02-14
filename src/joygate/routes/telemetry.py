from __future__ import annotations

import math
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from joygate.telemetry_logic import ALLOWED_TRUTH_INPUT_SOURCES

router = APIRouter()
SEGMENT_ID_RE = re.compile(r"^cell_\d+_\d+$")
MAX_SEGMENT_IDS_PER_REQUEST = 200
MAX_JOYKEY_LEN = 64
MAX_ROUTE_STR_LEN = 64


class SegmentPassedTelemetryRequest(BaseModel):
    joykey: str
    fleet_id: Optional[str] = None
    segment_ids: list[str]
    event_occurred_at: float | str
    truth_input_source: str


@router.post("/v1/telemetry/segment_passed", status_code=204)
def v1_telemetry_segment_passed(req: SegmentPassedTelemetryRequest, request: Request):
    """POST /v1/telemetry/segment_passed；走通过新鲜度信号，M14.3 调用 store.record_segment_passed_telemetry。"""
    if not isinstance(req.segment_ids, list) or len(req.segment_ids) < 1:
        raise HTTPException(status_code=400, detail="invalid segment_ids")
    if len(req.segment_ids) > MAX_SEGMENT_IDS_PER_REQUEST:
        raise HTTPException(status_code=400, detail="too many segment_ids")
    segment_ids_seen: set[str] = set()
    segment_ids_clean: list[str] = []
    for sid in req.segment_ids:
        if not isinstance(sid, str) or not (sid or "").strip():
            raise HTTPException(status_code=400, detail="invalid segment_ids")
        s = sid.strip()
        if sid != s or len(s) < 1 or len(s) > MAX_ROUTE_STR_LEN or not SEGMENT_ID_RE.fullmatch(s):
            raise HTTPException(status_code=400, detail="invalid segment_ids")
        if s not in segment_ids_seen:
            segment_ids_seen.add(s)
            segment_ids_clean.append(s)
    if not isinstance(req.joykey, str):
        raise HTTPException(status_code=400, detail="invalid joykey")
    s_joykey = req.joykey.strip()
    if not s_joykey or req.joykey != s_joykey or len(s_joykey) > MAX_JOYKEY_LEN:
        raise HTTPException(status_code=400, detail="invalid joykey")
    s_fleet_id: Optional[str] = None
    if req.fleet_id is not None:
        if not isinstance(req.fleet_id, str):
            raise HTTPException(status_code=400, detail="invalid fleet_id")
        s = req.fleet_id.strip()
        if req.fleet_id != s:
            raise HTTPException(status_code=400, detail="invalid fleet_id")
        s_fleet_id = s or None
        if s_fleet_id is not None and len(s_fleet_id) > MAX_ROUTE_STR_LEN:
            raise HTTPException(status_code=400, detail="invalid fleet_id")
    if not isinstance(req.truth_input_source, str):
        raise HTTPException(status_code=400, detail="invalid truth_input_source")
    s_truth = req.truth_input_source.strip()
    if not s_truth or req.truth_input_source != s_truth or len(s_truth) > MAX_ROUTE_STR_LEN:
        raise HTTPException(status_code=400, detail="invalid truth_input_source")
    if s_truth not in ALLOWED_TRUTH_INPUT_SOURCES:
        raise HTTPException(status_code=400, detail="invalid truth_input_source")
    if isinstance(req.event_occurred_at, (int, float)):
        if not math.isfinite(req.event_occurred_at) or req.event_occurred_at < 0:
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    elif isinstance(req.event_occurred_at, str):
        s_occurred = (req.event_occurred_at or "").strip()
        if req.event_occurred_at != s_occurred or len(s_occurred) > MAX_ROUTE_STR_LEN:
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
        try:
            float(s_occurred)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    else:
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    store = request.state.store
    try:
        store.record_segment_passed_telemetry(
            joykey=s_joykey,
            fleet_id=s_fleet_id,
            segment_ids=segment_ids_clean,
            event_occurred_at=req.event_occurred_at,
            truth_input_source=s_truth,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)
