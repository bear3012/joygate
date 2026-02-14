"""
M10 走通过新鲜度信号：仅解析时间、校验规则、委托 store 落库。
不触碰 hazards / incident / HARD_BLOCKED 任何逻辑。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

ALLOWED_FUTURE_SKEW_SECONDS = 60

# 与 FIELD_REGISTRY §3 truth_input_source 一致
ALLOWED_TRUTH_INPUT_SOURCES = {"SIMULATOR", "OCPP", "THIRD_PARTY_API", "QR_SCAN", "VISION"}


def _parse_event_occurred_at(value: float | str) -> float:
    """
    解析 event_occurred_at 为 epoch seconds (float)。供 segment_passed 及需解析该字段的接口复用。
    - number：当作 epoch seconds，必须 >0
    - string：ISO8601（含 Z/z 或 offset）；解析失败 -> ValueError("invalid event_occurred_at")
    仅用标准库 datetime/time，不引入第三方库。
    """
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts <= 0:
            raise ValueError("event_occurred_at must be positive")
        return ts
    if isinstance(value, str):
        s = (value or "").strip()
        if not s:
            raise ValueError("event_occurred_at string empty")
        try:
            # 支持 ISO8601 含 Z/z 或 +00:00 / -05:00 等（Python 3.7+ fromisoformat 不认 Z，先替换）
            s_norm = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
            dt = datetime.fromisoformat(s_norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            raise ValueError("invalid event_occurred_at")
    raise ValueError("event_occurred_at must be number or ISO8601 string")


def handle_segment_passed(store: Any, req: Any) -> None:
    """
    校验 event_occurred_at 与 truth_input_source，对每个 segment_id 调用 store.record_segment_passed。
    不触碰 hazards/incident/hard_blocked。
    """
    event_ts = _parse_event_occurred_at(req.event_occurred_at)
    server_now = time.time()
    if event_ts > server_now + ALLOWED_FUTURE_SKEW_SECONDS:
        raise ValueError("event_occurred_at too far in future")
    if req.truth_input_source not in ALLOWED_TRUTH_INPUT_SOURCES:
        raise ValueError(f"invalid truth_input_source: {req.truth_input_source}")

    joykey = (req.joykey or "").strip()
    if not joykey:
        raise ValueError("invalid joykey")
    fleet_id = (req.fleet_id or "").strip() or None

    for segment_id in req.segment_ids:
        seg = (segment_id or "").strip()
        if not seg:
            raise ValueError("invalid segment_ids")
        store.record_segment_passed(
            segment_id=seg,
            event_ts=event_ts,
            joykey=joykey,
            truth_input_source=req.truth_input_source,
            fleet_id=fleet_id,
        )
