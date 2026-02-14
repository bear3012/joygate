from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from joygate.store import ALLOWED_INCIDENT_STATUSES, ALLOWED_INCIDENT_TYPES
from joygate.routes._input_norm import (
    norm_evidence_refs,
    norm_optional_str,
    norm_required_str,
)
from joygate.config import (
    WEBHOOK_TIMEOUT_SECONDS,
    WEBHOOK_RETRY_MAX_ATTEMPTS,
    WEBHOOK_RETRY_BACKOFF_SECONDS,
)

router = APIRouter()


class ReportBlockedIn(BaseModel):
    charger_id: str
    incident_type: str
    snapshot_ref: Optional[str] = None
    evidence_refs: Optional[list[str]] = None


class UpdateStatusIn(BaseModel):
    incident_id: str
    incident_status: str


class IncidentItemOut(BaseModel):
    incident_id: str
    incident_type: str
    incident_status: str
    charger_id: str | None
    segment_id: str | None
    snapshot_ref: str | None
    evidence_refs: list[str] | None
    ai_insights: list[dict[str, Any]] | None


class IncidentListOut(BaseModel):
    incidents: list[IncidentItemOut]


class IncidentsReportBlockedOut(BaseModel):
    incident_id: str


MAX_DELIVERIES_PER_DISPATCH = 50  # 单次派发 delivery 上限，内部常量
MAX_EVENTS_SCAN_PER_DISPATCH = 200  # 单次扫描事件数上限，超出部分 put_back 下一轮
MAX_INCIDENT_ID_LEN = 64
MAX_SNAPSHOT_REF_LEN = 64
MAX_CHARGER_ID_LEN = 64
MAX_INCIDENT_TYPE_LEN = 32
MAX_EVIDENCE_REFS = 20
MAX_EVIDENCE_REF_LEN = 256

# 路由层统一限长（report_blocked 已有校验不动；witness/webhook 入口用）
MAX_ROUTE_STR_LEN = 64
MAX_EVIDENCE_REFS_ROUTE = 5
MAX_EVIDENCE_REF_LEN_ROUTE = 120


def _validate_required_str(value: Any, field_name: str, max_len: int = MAX_ROUTE_STR_LEN) -> str:
    """str -> strip；原始!=strip 或 空 或 超长 -> 400 invalid <field>。"""
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    s = value.strip()
    if value != s or not s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    return s


def _validate_optional_str(value: Any, field_name: str, max_len: int = MAX_ROUTE_STR_LEN) -> Optional[str]:
    """可选字符串：None 返回 None；否则同 _validate_required_str 规则（空 strip 也 400）。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    s = value.strip()
    if value != s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    return s if s else None


def _validate_evidence_refs_route(refs: Any, field_name: str = "evidence_refs") -> Optional[list[str]]:
    """evidence_refs：list，最多 5 项，每项 str strip 无空白、长度<=120。"""
    if refs is None:
        return None
    if not isinstance(refs, list):
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    if len(refs) > MAX_EVIDENCE_REFS_ROUTE:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, str):
            raise HTTPException(status_code=400, detail=f"invalid {field_name}")
        s = ref.strip()
        if ref != s or not s or len(s) > MAX_EVIDENCE_REF_LEN_ROUTE:
            raise HTTPException(status_code=400, detail=f"invalid {field_name}")
        out.append(s)
    return out


def _dispatch_webhook_outbox(store, background_tasks: BackgroundTasks) -> None:
    events = store.drain_webhook_outbox()
    if not events:
        return
    to_scan = events[:MAX_EVENTS_SCAN_PER_DISPATCH]
    rest = events[MAX_EVENTS_SCAN_PER_DISPATCH:]
    added_deliveries = 0
    for i, event in enumerate(to_scan):
        try:
            event_type = event.get("event_type")
            if not isinstance(event_type, str) or not event_type.strip():
                continue
            targets = store.list_enabled_webhook_targets_for_event(event_type)
            valid_targets = [
                t
                for t in targets
                if t.get("subscription_id")
                and isinstance(t.get("target_url"), str)
                and (t.get("target_url") or "").strip()
            ]
            if not valid_targets:
                continue
            remaining_budget = MAX_DELIVERIES_PER_DISPATCH - added_deliveries
            # 一个 event 要么全派发要么不派发；budget 不足则整包延后，此分支不创建任何 delivery（避免重复派发）
            if remaining_budget <= 0 or added_deliveries + len(valid_targets) > MAX_DELIVERIES_PER_DISPATCH:
                store.put_back_webhook_outbox([event] + to_scan[i + 1 :] + rest)
                return
            for target in valid_targets:
                subscription_id = target.get("subscription_id")
                target_url = (target.get("target_url") or "").strip()
                secret = target.get("secret")
                delivery_id = store.create_webhook_delivery_if_absent(event, subscription_id, target_url)
                if delivery_id is None:
                    continue  # 已存在相同 event_id+subscription_id，不重复发送
                background_tasks.add_task(
                    store.process_webhook_delivery,
                    delivery_id,
                    target_url,
                    secret,
                    event,
                    WEBHOOK_TIMEOUT_SECONDS,
                    WEBHOOK_RETRY_MAX_ATTEMPTS,
                    WEBHOOK_RETRY_BACKOFF_SECONDS,
                )
                added_deliveries += 1
        except Exception:
            store.put_back_webhook_outbox([event] + to_scan[i + 1 :] + rest)
            return
    if rest:
        store.put_back_webhook_outbox(rest)


@router.get("/v1/incidents", response_model=IncidentListOut)
def v1_incidents(
    request: Request,
    incident_id: Optional[str] = None,
    incident_type: Optional[str] = None,
    incident_status: Optional[str] = None,
    charger_id: Optional[str] = None,
    segment_id: Optional[str] = None,
):
    """返回事件列表，严格符合 FIELD_REGISTRY IncidentList：{ incidents: [...] }。"""
    incident_type_for_list: Optional[str] = None
    if incident_type is not None:
        if not isinstance(incident_type, str):
            raise HTTPException(status_code=400, detail="invalid incident_type")
        it_clean = incident_type.strip()
        if not it_clean or incident_type != it_clean or len(it_clean) > MAX_INCIDENT_TYPE_LEN:
            raise HTTPException(status_code=400, detail="invalid incident_type")
        if it_clean not in ALLOWED_INCIDENT_TYPES:
            raise HTTPException(status_code=400, detail=f"invalid incident_type: {it_clean}")
        incident_type_for_list = it_clean
    charger_id_for_list: Optional[str] = None
    if charger_id is not None:
        if not isinstance(charger_id, str):
            raise HTTPException(status_code=400, detail="invalid charger_id")
        cid_clean = charger_id.strip()
        if not cid_clean or charger_id != cid_clean or len(cid_clean) > MAX_CHARGER_ID_LEN:
            raise HTTPException(status_code=400, detail="invalid charger_id")
        charger_id_for_list = cid_clean
    incident_status_for_list: Optional[str] = None
    if incident_status is not None:
        if not isinstance(incident_status, str):
            raise HTTPException(status_code=400, detail="invalid incident_status")
        st_clean = incident_status.strip()
        if not st_clean or incident_status != st_clean or len(st_clean) > MAX_ROUTE_STR_LEN:
            raise HTTPException(status_code=400, detail="invalid incident_status")
        if st_clean not in ALLOWED_INCIDENT_STATUSES:
            raise HTTPException(status_code=400, detail="invalid incident_status")
        incident_status_for_list = st_clean
    incident_id_for_list: Optional[str] = None
    if incident_id is not None:
        if not isinstance(incident_id, str):
            raise HTTPException(status_code=400, detail="invalid incident_id")
        sid = (incident_id or "").strip()
        if not sid or incident_id != sid or len(sid) > MAX_INCIDENT_ID_LEN:
            raise HTTPException(status_code=400, detail="invalid incident_id")
        incident_id_for_list = sid
    segment_id_for_list = norm_optional_str("segment_id", segment_id, MAX_INCIDENT_ID_LEN) if segment_id is not None else None

    store = request.state.store
    results = store.list_incidents(
        incident_id=incident_id_for_list,
        incident_type=incident_type_for_list,
        incident_status=incident_status_for_list,
        charger_id=charger_id_for_list,
        segment_id=segment_id_for_list,
    )
    return {"incidents": results}


@router.post("/v1/incidents/report_blocked", response_model=IncidentsReportBlockedOut)
def v1_incidents_report_blocked(req: ReportBlockedIn, request: Request, background_tasks: BackgroundTasks):
    """创建一条 blocked 类事件，返回 incident_id；入口统一 64 上限、strip、禁止前后空白；evidence_refs 最多 5 条每条约 120。"""
    charger_id_clean = norm_required_str("charger_id", req.charger_id, MAX_CHARGER_ID_LEN)
    incident_type_clean = norm_required_str("incident_type", req.incident_type, MAX_INCIDENT_ID_LEN)
    if incident_type_clean not in ALLOWED_INCIDENT_TYPES:
        raise HTTPException(status_code=400, detail="invalid incident_type")
    snapshot_ref_clean = norm_optional_str("snapshot_ref", req.snapshot_ref, MAX_SNAPSHOT_REF_LEN)
    evidence_refs_for_store = norm_evidence_refs(req.evidence_refs)
    store = request.state.store
    try:
        incident_id = store.report_blocked_incident(
            charger_id=charger_id_clean,
            incident_type=incident_type_clean,
            snapshot_ref=snapshot_ref_clean,
            evidence_refs=evidence_refs_for_store,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return {"incident_id": incident_id}


@router.post("/v1/incidents/update_status")
def v1_incidents_update_status(req: UpdateStatusIn, request: Request, background_tasks: BackgroundTasks):
    """更新事件状态；严格符合 FIELD_REGISTRY POST /v1/incidents/update_status，成功 204 No Content。"""
    if req.incident_status not in ALLOWED_INCIDENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"invalid incident_status: {req.incident_status}")
    if not isinstance(req.incident_id, str):
        raise HTTPException(status_code=400, detail="invalid incident_id")
    iid_stripped = (req.incident_id or "").strip()
    if not iid_stripped or req.incident_id != iid_stripped or len(iid_stripped) > MAX_INCIDENT_ID_LEN:
        raise HTTPException(status_code=400, detail="invalid incident_id")
    store = request.state.store
    try:
        store.update_incident_status(req.incident_id, req.incident_status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown incident_id: {req.incident_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _dispatch_webhook_outbox(store, background_tasks)
    return Response(status_code=204)
