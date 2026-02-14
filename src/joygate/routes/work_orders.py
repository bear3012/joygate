"""
M15 工单闭环：POST /v1/work_orders/report。
仅当 work_order_status=DONE 且 segment_id 非空时，可解封该 segment 的 HARD_BLOCKED；否则不解封。
入口统一：str strip、禁止前后空白、长度 64；evidence_refs 最多 5 条每条约 120。
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from joygate.store import ALLOWED_WORK_ORDER_STATUSES
from joygate.routes.incidents import _dispatch_webhook_outbox
from joygate.routes._input_norm import (
    norm_evidence_refs,
    norm_optional_str,
    norm_required_str,
)

router = APIRouter()
MAX_ROUTE_STR_LEN = 64


class WorkOrderReportIn(BaseModel):
    """FIELD_REGISTRY POST /v1/work_orders/report 输入。"""
    work_order_id: str
    incident_id: Optional[str] = None
    segment_id: Optional[str] = None
    charger_id: Optional[str] = None
    work_order_status: str
    event_occurred_at: float | str
    evidence_refs: Optional[list[str]] = None


@router.post("/v1/work_orders/report", status_code=204)
def v1_work_orders_report(req: WorkOrderReportIn, request: Request, background_tasks: BackgroundTasks):
    """M15：工单上报。入口统一 strip/64；event_occurred_at 若 str 则 len≤64 禁止前后空白；evidence_refs 5/120。"""
    if not isinstance(req.work_order_status, str):
        raise HTTPException(status_code=400, detail="invalid work_order_status")
    wo_status = req.work_order_status.strip()
    if not wo_status or req.work_order_status != wo_status or len(wo_status) > MAX_ROUTE_STR_LEN:
        raise HTTPException(status_code=400, detail="invalid work_order_status")
    if wo_status not in ALLOWED_WORK_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="invalid work_order_status")
    work_order_id = norm_required_str("work_order_id", req.work_order_id, MAX_ROUTE_STR_LEN)
    incident_id = norm_optional_str("incident_id", req.incident_id, MAX_ROUTE_STR_LEN)
    segment_id = norm_optional_str("segment_id", req.segment_id, MAX_ROUTE_STR_LEN)
    charger_id = norm_optional_str("charger_id", req.charger_id, MAX_ROUTE_STR_LEN)
    evidence_refs_out = norm_evidence_refs(req.evidence_refs)
    if isinstance(req.event_occurred_at, (int, float)):
        if not math.isfinite(req.event_occurred_at) or req.event_occurred_at < 0:
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
        event_occurred_at = req.event_occurred_at
    elif isinstance(req.event_occurred_at, str):
        s = (req.event_occurred_at or "").strip()
        if req.event_occurred_at != s or len(s) > MAX_ROUTE_STR_LEN:
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
        try:
            event_occurred_at = float(s)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    else:
        raise HTTPException(status_code=400, detail="invalid event_occurred_at")
    store = request.state.store
    try:
        store.report_work_order(
            work_order_id=work_order_id,
            incident_id=incident_id,
            segment_id=segment_id,
            charger_id=charger_id,
            work_order_status=wo_status,
            event_occurred_at=event_occurred_at,
            evidence_refs=evidence_refs_out,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return Response(status_code=204)
