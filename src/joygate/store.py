# src/joygate/store.py
"""
JoyGate 统一状态仓库：管理 chargers / holds / quota，支持 /v1/snapshot。
所有字段/枚举/错误码严格遵循 FIELD_REGISTRY.md，不新增未登记项。
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Any

from joygate.ai_jobs import (
    AI_JOB_TYPE_DISPATCH_EXPLAIN,
    AI_JOB_TYPE_POLICY_SUGGEST,
    AI_JOB_TYPE_VISION_AUDIT,
    ALLOWED_AI_JOB_STATUS,
    TERMINAL_AI_JOB_STATUS,
    cleanup_ai_jobs_locked,
    create_dispatch_explain_job_locked,
    create_policy_suggest_job_locked,
    create_vision_audit_job_locked,
    tick_ai_jobs_locked,
    list_ai_jobs_locked,
)
from joygate.incidents_logic import (
    apply_witness_sla_downgrade_locked,
    build_incidents_snapshot,
    cleanup_incidents_locked,
    find_incident_by_id,
    report_blocked_incident_locked,
)
from joygate.witness_logic import witness_respond_locked
from joygate.dashboard_logic import build_incidents_daily_report
from joygate.config import (
    AI_BUDGET_DAY_SECONDS,
    AI_JOB_RETENTION_SECONDS,
    ALLOWED_WITNESS_JOYKEYS,
    DASHBOARD_DAY_MODE,
    DASHBOARD_TZ_OFFSET_HOURS,
    DEMO_DAY_SECONDS,
    INCIDENT_STALE_MINUTES,
    minute_to_seconds,
    JOYGATE_AI_DAILY_BUDGET_CALLS,
    JOYKEY_TO_POINTS,
    JOYKEY_TO_VENDOR,
    MAX_INCIDENTS,
    POLICY_CONFIG,
    TTL_RESOLVED_HIGH_PRIORITY_SECONDS,
    TTL_RESOLVED_LOW_PRIORITY_SECONDS,
    WITNESS_CERTIFIED_POINTS_THRESHOLD,
    WITNESS_MIN_CERTIFIED_SUPPORT_RISKY,
    WITNESS_MIN_DISTINCT_VENDORS,
    WITNESS_MIN_DISTINCT_VENDORS_RISKY,
    WITNESS_MIN_MARGIN_RISKY,
    WITNESS_SCORE_REQUIRED,
    WITNESS_SCORE_REQUIRED_RISKY,
    WITNESS_SCORE_REQUIRED_SINGLE_VENDOR,
    WITNESS_SLA_TIMEOUT_MINUTES,
    WITNESS_VENDOR_DECAY_GAMMA,
    WITNESS_VOTES_REQUIRED,
    JOYGATE_WEBHOOK_ALLOW_HTTP,
    JOYGATE_WEBHOOK_ALLOW_LOCALHOST,
    WEBHOOK_DELIVERY_RETENTION_SECONDS,
)
from joygate.sim_render import render_sim_snapshot_png
from joygate.telemetry_logic import (
    ALLOWED_FUTURE_SKEW_SECONDS,
    ALLOWED_TRUTH_INPUT_SOURCES,
    _parse_event_occurred_at,
)
from joygate.vision_audit_report_logic import upsert_ai_insight, generate_vision_audit_result
from joygate.webhook_target_url import validate_webhook_target_url
from joygate.webhooks_logic import send_webhook_with_retry
# --- 常量（与 FIELD_REGISTRY 一致）---
SUMMARY_CAP_LEN = 512
_TRUNCATED_SUFFIX = "...(truncated)"


def _cap_summary(summary: str, max_len: int = SUMMARY_CAP_LEN) -> str:
    """Ledger summary 长度上限；超出则截断并追加 ...(truncated)。"""
    if not summary or len(summary) <= max_len:
        return summary or ""
    return summary[: max_len - len(_TRUNCATED_SUFFIX)] + _TRUNCATED_SUFFIX


HOLD_TTL_SECONDS = 180
SLOT_STATE_FREE = "FREE"
SLOT_STATE_HELD = "HELD"
SLOT_STATE_CHARGING = "CHARGING"
ERROR_QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
ERROR_RESOURCE_BUSY = "RESOURCE_BUSY"
MESSAGE_QUOTA = "single active hold per joykey"
MESSAGE_BUSY = "resource already held"

# 入口字符串长度上限（内部防污染，与 FIELD_REGISTRY 对齐）
MAX_ID_LEN = 64
MAX_CHARGER_ID_LEN = 64
MAX_INCIDENT_ID_LEN = 64
MAX_INCIDENT_TYPE_LEN = 64
MAX_SNAPSHOT_REF_LEN = 256
MAX_CONTEXT_REF_LEN = 256
MAX_TELEMETRY_JOYKEY_LEN = 128
MAX_POINTS_EVENT_ID_LEN = 64

DEFAULT_CHARGER_IDS = [f"charger-{i:03d}" for i in range(1, 11)]

# --- Incident 相关枚举（单一定义点，严格对齐 FIELD_REGISTRY）---
ALLOWED_INCIDENT_TYPES = {
    "NO_PLUG",
    "BLOCKED_BY_OTHER",
    "BLOCKED",
    "HIJACKED",
    "UNKNOWN_OCCUPANCY",
    "OVERSTAY",
    "NO_SHOW",
    "OTHER",
}

ALLOWED_INCIDENT_STATUSES = {
    "OPEN",
    "RESOLVED",
    "ESCALATED",
    "UNDER_OBSERVATION",
    "EVIDENCE_CONFIRMED",
}

# 严重事件状态（仅用 FIELD_REGISTRY 已有 incident_status 拼写，供 dashboard 统计；不新增枚举）
SEVERE_INCIDENT_STATUSES = {"ESCALATED", "EVIDENCE_CONFIRMED"}

# hazard_status 用于 segment 维度（与 FIELD_REGISTRY 一致，最小集合）
ALLOWED_HAZARD_STATUSES = {"BLOCKED", "CLEAR"}
# segment_state（witness 通行状态，FIELD_REGISTRY；不写入系统 OPEN/SOFT/HARD）
ALLOWED_SEGMENT_STATES = {"PASSABLE", "BLOCKED", "UNKNOWN"}
# work_order_status（FIELD_REGISTRY §3；仅 DONE + segment_id 可解封 HARD_BLOCKED）
ALLOWED_WORK_ORDER_STATUSES = {"OPEN", "IN_PROGRESS", "DONE", "FAILED", "ESCALATED"}

# 合法状态流转（仅用已存在 incident_status；允许幂等同状态）
ALLOWED_INCIDENT_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"OPEN", "ESCALATED", "UNDER_OBSERVATION", "EVIDENCE_CONFIRMED", "RESOLVED"},
    "ESCALATED": {"ESCALATED", "UNDER_OBSERVATION", "EVIDENCE_CONFIRMED", "RESOLVED"},
    "UNDER_OBSERVATION": {"UNDER_OBSERVATION", "EVIDENCE_CONFIRMED", "ESCALATED", "RESOLVED"},
    "EVIDENCE_CONFIRMED": {"EVIDENCE_CONFIRMED", "RESOLVED"},
    "RESOLVED": {"RESOLVED"},
}

LOW_RETENTION_INCIDENT_TYPES = {"NO_SHOW", "OTHER", "OVERSTAY", "NO_PLUG"}
# M9.4 Outbound Webhooks（内部上限，不进 FIELD_REGISTRY）
MAX_WEBHOOK_OUTBOX = 1000
MAX_WEBHOOK_SUBSCRIPTIONS = 50  # 与 dispatch 单次 budget 对齐，enabled 订阅数上限
# M10 走通过新鲜度信号（segment_passed）最多保留条数
MAX_SEGMENT_PASSED = 200
# M12A-1 每 joykey 保留的轨迹 segment 数量（ring buffer）
ROBOT_TRACKS_MAX = 50
# M11 审计账本 sidecar_safety_events 内存 cap（internal，不进 FIELD_REGISTRY）
MAX_SIDECAR_SAFETY_EVENTS = 500
# M14.3 segment witness 证据事件列表 cap（内部，不进 FIELD_REGISTRY）
MAX_SEGMENT_WITNESS_EVENTS = 1000
# 每个 segment 最多保留的 points_event_id 数量（按最旧淘汰）
MAX_POINTS_EVENT_IDS_PER_SEGMENT = 500
# Proactive congestion：120s 窗口内 ≥3 个不同 joykey 的 reserve 409 → ledger POLICY_SUGGESTED（internal，不进 FIELD_REGISTRY）
PROACTIVE_CONGESTION_WINDOW_SECONDS = 120
PROACTIVE_CONGESTION_DISTINCT_JOYKEYS_THRESHOLD = 3
PROACTIVE_DELAY_CHARGING_SECONDS = 120
MAX_PROACTIVE_BUSY_EVENTS = 1000
MAX_DECISIONS = 2000
MAX_PROACTIVE_SUGGESTION_KEYS = 5000

# M16 信誉/计分（内部 cap，不进 FIELD_REGISTRY）
MAX_SCORE_EVENTS = 2000
NEUTRAL_ROBOT_SCORE = 60
MIN_ROBOT_SCORE = 0
MAX_ROBOT_SCORE = 100
SUSPICIOUS_SCORE_THRESHOLD = 50
SCORE_DELTA_WITNESS_VERIFIED = 2

# webhook_event_type（严格对齐 FIELD_REGISTRY）
ALLOWED_WEBHOOK_EVENT_TYPES = {
    "INCIDENT_CREATED",
    "INCIDENT_STATUS_CHANGED",
    "AI_JOB_STATUS_CHANGED",
    "HAZARD_STATUS_CHANGED",
    "WORK_ORDER_STATUS_CHANGED",
    "HOLD_CREATED",
    "HOLD_EXPIRED",
    "OTHER",
}


def _iso_utc(ts: float) -> str:
    """将 Unix 时间戳转为 ISO8601 UTC 字符串，供 snapshot_at / expires_at 使用。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _parse_recheck_due_at(recheck_due_at: str) -> float | None:
    """
    仅内部用：将 recheck_due_at（_iso_utc 产生的 YYYY-MM-DDTHH:MM:SSZ）转为 UTC unix ts。
    解析失败视为不可处理，返回 None（调用方 skip 该 hazard，不抛异常）。
    """
    if not recheck_due_at or not isinstance(recheck_due_at, str):
        return None
    s = (recheck_due_at or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _int_or_default(v: Any, default: int) -> int:
    """None -> default；int/float/str 数字 -> int(v)；其他异常 -> default。"""
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _clamp_score(x: int | float) -> int:
    """M16：限制 robot_score 到 [MIN_ROBOT_SCORE, MAX_ROBOT_SCORE]。"""
    try:
        v = int(x)
    except (TypeError, ValueError):
        return NEUTRAL_ROBOT_SCORE
    if v < MIN_ROBOT_SCORE:
        return MIN_ROBOT_SCORE
    if v > MAX_ROBOT_SCORE:
        return MAX_ROBOT_SCORE
    return v


def _tier_for_score(score: int) -> str:
    """M16：按 FIELD_REGISTRY robot_tier 枚举 A/B/C/D 映射。"""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def _get_vendor_for_joykey(joykey: str) -> str | None:
    """M16：用 config JOYKEY_TO_VENDOR 查厂商（fleet_id）。"""
    return JOYKEY_TO_VENDOR.get(joykey)


def _list_segment_passed_signals_locked(store: "JoyGateStore", limit: int) -> list[dict[str, Any]]:
    """在已持 store._lock 时调用，返回按 segment_id 排序的 signal 列表，截断到 limit。"""
    out: list[dict[str, Any]] = []
    for sid, rec in sorted(store._segment_passed.items(), key=lambda x: x[0]):
        if not isinstance(rec, dict):
            continue
        out.append({
            "segment_id": sid,
            "last_passed_at": rec.get("last_passed_at") or _iso_utc(rec.get("last_passed_ts") or 0),
            "joykey": rec.get("joykey") or "",
            "truth_input_source": rec.get("truth_input_source") or "",
            "fleet_id": rec.get("fleet_id"),
        })
        if len(out) >= limit:
            break
    return out


def _normalize_evidence_refs(refs: list[str] | None, max_len: int = 120, max_count: int = 5) -> list[str]:
    """evidence_refs 防污染：最多 max_count 条，每项 str、strip 非空、长度<=max_len。"""
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for r in refs:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if not s or len(s) > max_len:
            continue
        out.append(s)
        if len(out) >= max_count:
            break
    return out


def _norm_required_str(name: str, v: Any, max_len: int) -> str:
    """必填字符串：str、strip 非空、禁止前后空白、长度<=max_len；失败 raise ValueError('invalid {name}')。"""
    if not isinstance(v, str):
        raise ValueError(f"invalid {name}")
    raw, s = v, v.strip()
    if not s or raw != s or len(s) > max_len:
        raise ValueError(f"invalid {name}")
    return s


def _norm_optional_str(name: str, v: Any | None, max_len: int) -> str | None:
    """可选字符串：None 或 str；strip 后空当 None；禁止前后空白、长度<=max_len；失败 raise ValueError('invalid {name}')。"""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"invalid {name}")
    raw, s = v, v.strip()
    if not s:
        return None
    if raw != s or len(s) > max_len:
        raise ValueError(f"invalid {name}")
    return s


def _today_date_in_tz(tz_name: str) -> str:
    """返回当前在指定时区的日期 YYYY-MM-DD。仅支持 Asia/Taipei（UTC+8），否则 raise ValueError。"""
    if tz_name != "Asia/Taipei":
        raise ValueError(f"unsupported tz_name: {tz_name!r}, only Asia/Taipei is supported")
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def _ts_to_date_in_tz(ts: float, tz_name: str) -> str:
    """将 Unix 时间戳转为该时区下的日期 YYYY-MM-DD。仅支持 Asia/Taipei（UTC+8），否则 raise ValueError。"""
    if tz_name != "Asia/Taipei":
        raise ValueError(f"unsupported tz_name: {tz_name!r}, only Asia/Taipei is supported")
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")


def _date_str_with_offset(ts: float, offset_hours: int) -> str:
    """将 Unix 时间戳按 offset 时区（UTC+offset_hours）转为 YYYY-MM-DD。内部用于 CALENDAR 模式。"""
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")


class JoyGateStore:
    """
    管理充电桩槽位、占位、配额；并发安全（单 Lock）；支持过期清理与快照。
    """

    def __init__(self, charger_ids: list[str] | None = None, ttl_seconds: int = HOLD_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._lock = Lock()
        # Demo Clock 基准：store 启动时间（供 dashboard DEMO 日历使用）
        self._boot_ts = time.time()
        ids = charger_ids or DEFAULT_CHARGER_IDS
        # charger_id -> { slot_state, hold_id, joykey }
        self._slots: dict[str, dict[str, Any]] = {
            cid: {"slot_state": SLOT_STATE_FREE, "hold_id": None, "joykey": None}
            for cid in ids
        }
        # hold_id -> { charger_id, joykey, expires_at (float) }
        self._holds: dict[str, dict[str, Any]] = {}
        # joykey -> hold_id（单 joykey 单占位）
        self._joykey_to_hold_id: dict[str, str] = {}
        # 事件列表（内部项含 created_at，对外 IncidentItem 不暴露 created_at）
        self._incidents: list[dict[str, Any]] = []
        # M8 witness 投票：incident_id -> {tally, seen_points_event_ids, seen_witness_joykeys, total}（不出 API）
        self._witness_by_incident: dict[str, dict[str, Any]] = {}
        # M9.1 AI Jobs（仅内存态，不出 /v1/snapshot）
        self._ai_jobs: dict[str, dict[str, Any]] = {}
        self._ai_job_queue: list[str] = []
        self._active_ai_job_by_incident: dict[str, str] = {}
        # M9.4 Outbound Webhooks（内存态）
        self._webhook_subscriptions: dict[str, dict[str, Any]] = {}
        self._webhook_outbox: list[dict[str, Any]] = []
        self._webhook_deliveries: list[dict[str, Any]] = []
        # M9 Segment witness / Hazards（内存态）
        self._hazards_by_segment: dict[str, dict[str, Any]] = {}
        self._witness_by_segment: dict[str, dict[str, Any]] = {}
        # M10 走通过新鲜度信号（仅信号，不改 hazard_status）
        self._segment_passed: dict[str, dict[str, Any]] = {}
        # M12A-1 机器人轨迹：joykey -> 最近 N 个 segment_id（ring buffer，仅 cell_x_y 格式）
        self._robot_tracks: dict[str, list[str]] = {}
        # M11 审计账本（内存态；audit_status 默认值来自 FIELD_REGISTRY）
        self._audit_status: dict[str, Any] = {
            "audit_data_mode": "NO_RAW_MEDIA_STORED",
            "retention_seconds": 0,
            "frame_disposition": "NOT_CAPTURED",
            "last_vision_audit_at": None,
        }
        self._decisions: list[dict[str, Any]] = []
        self._sidecar_safety_events: list[dict[str, Any]] = []
        # Proactive congestion：409 事件列表 + 去重 key（FIFO 淘汰）
        self._proactive_busy_events: list[dict[str, Any]] = []
        self._proactive_suggestion_keys: set[str] = set()
        self._proactive_suggestion_keys_fifo: list[str] = []
        # M14.3 segment witness 证据事件（内部；按 freshness 窗口 + cap 裁剪）
        self._segment_witness_events: list[dict[str, Any]] = []
        # M16 信誉/计分（内存态，不进 /v1/snapshot）
        self._reputation_by_joykey: dict[str, dict[str, Any]] = {}
        self._score_events: list[dict[str, Any]] = []
        self._score_event_ids: set[str] = set()
        self._vendor_scores: dict[str, dict[str, Any]] = {}
        # M12A-1 每日 AI 调用计数（用于 budget；日期变更时重置）
        self._ai_daily_calls_date: str | None = None
        self._ai_daily_calls_count: int = 0

    def get_ai_job_by_report_id(self, ai_report_id: str) -> dict[str, Any] | None:
        """M13.1：按 ai_report_id 查找 job（内部用）；不存在返回 None。"""
        with self._lock:
            for job in self._ai_jobs.values():
                if isinstance(job, dict) and job.get("ai_report_id") == ai_report_id:
                    return dict(job)
            return None

    def ledger_has_policy_suggested(self, ai_report_id: str) -> bool:
        """M13.1：ledger 中是否存在该 ai_report_id 的 decision_type=POLICY_SUGGESTED（内部用）。"""
        with self._lock:
            for d in self._decisions:
                if isinstance(d, dict) and d.get("decision_type") == "POLICY_SUGGESTED" and d.get("ai_report_id") == ai_report_id:
                    return True
            return False

    def get_policy(self) -> dict[str, Any]:
        """M14.1：返回制度参数（FIELD_REGISTRY §4 Policy Config）；只读副本，默认值集中在 joygate.config。"""
        return dict(POLICY_CONFIG)

    def get_audit_ledger(self) -> dict[str, Any]:
        """M11：返回审计账本快照；audit_status 来自 store，不写死。返回副本避免外部修改。"""
        with self._lock:
            return {
                "audit_status": dict(self._audit_status),
                "decisions": [dict(d) for d in self._decisions],
                "sidecar_safety_events": [dict(e) for e in self._sidecar_safety_events],
            }

    def append_sidecar_safety_event(self, payload: dict[str, Any]) -> None:
        """M11：追加一条 sidecar 安全事件；生成 sidecar_event_id；cap 最旧淘汰。"""
        with self._lock:
            event_id = f"sse_{uuid.uuid4().hex[:12]}"
            rec = {
                "sidecar_event_id": event_id,
                "suggestion_id": payload.get("suggestion_id"),
                "joykey": payload.get("joykey"),
                "fleet_id": payload.get("fleet_id"),
                "oem_result": payload.get("oem_result"),
                "fallback_reason": payload.get("fallback_reason"),
                "observed_by": payload.get("observed_by"),
                "observed_at": payload.get("observed_at"),
            }
            self._sidecar_safety_events.append(rec)
            while len(self._sidecar_safety_events) > MAX_SIDECAR_SAFETY_EVENTS:
                self._sidecar_safety_events.pop(0)

    def purge_expired(self) -> None:
        """清理已过期的 hold，并将对应 charger 置为 FREE。必须在持有 _lock 时调用。"""
        now = time.time()
        to_remove = [
            (hid, rec)
            for hid, rec in self._holds.items()
            if rec["expires_at"] <= now
        ]
        for hold_id, rec in to_remove:
            charger_id = rec["charger_id"]
            joykey = rec["joykey"]
            self._holds.pop(hold_id, None)
            self._joykey_to_hold_id.pop(joykey, None)
            if charger_id in self._slots:
                self._slots[charger_id] = {
                    "slot_state": SLOT_STATE_FREE,
                    "hold_id": None,
                    "joykey": None,
                }

    def _record_proactive_busy_event_locked(self, charger_id: str, joykey: str, now: float) -> None:
        """在锁内调用：记录一次 reserve 409（资源忙）；按窗口裁剪并 cap 列表长度。"""
        self._proactive_busy_events.append({"charger_id": charger_id, "joykey": joykey, "ts": now})
        cutoff = now - PROACTIVE_CONGESTION_WINDOW_SECONDS
        while self._proactive_busy_events and self._proactive_busy_events[0].get("ts", 0) < cutoff:
            self._proactive_busy_events.pop(0)
        while len(self._proactive_busy_events) > MAX_PROACTIVE_BUSY_EVENTS:
            self._proactive_busy_events.pop(0)

    def _maybe_emit_proactive_delay_suggestions_locked(self, charger_id: str, now: float) -> None:
        """在锁内调用：若该 charger 在窗口内 ≥3 个不同 joykey 的 409，则对每个 joykey 去重写入一条 POLICY_SUGGESTED decision。"""
        cutoff = now - PROACTIVE_CONGESTION_WINDOW_SECONDS
        events_for_charger = [
            e for e in self._proactive_busy_events
            if e.get("charger_id") == charger_id and e.get("ts", 0) >= cutoff
        ]
        distinct_joykeys = list({e.get("joykey") for e in events_for_charger if e.get("joykey")})
        if len(distinct_joykeys) < PROACTIVE_CONGESTION_DISTINCT_JOYKEYS_THRESHOLD:
            return
        bucket = int(now // PROACTIVE_CONGESTION_WINDOW_SECONDS)
        for joykey in distinct_joykeys:
            key = f"{charger_id}:{joykey}:bucket:{bucket}"
            if key in self._proactive_suggestion_keys:
                continue
            raw_summary = (
                f"proactive congestion → suggest delay_charging_seconds={PROACTIVE_DELAY_CHARGING_SECONDS}; "
                f"charger_id={charger_id}, joykey={joykey}, window_sec={PROACTIVE_CONGESTION_WINDOW_SECONDS}, distinct={len(distinct_joykeys)}"
            )
            decision_id = f"dec_{uuid.uuid4().hex[:12]}"
            self._decisions.append({
                "decision_id": decision_id,
                "decision_type": "POLICY_SUGGESTED",
                "decision_basis": "POLICY",
                "incident_id": None,
                "hold_id": None,
                "charger_id": charger_id,
                "segment_id": None,
                "ai_report_id": None,
                "evidence_refs": None,
                "summary": _cap_summary(raw_summary),
                "prev_bundle_hash": None,
                "bundle_hash": None,
                "created_at": now,
            })
            while len(self._decisions) > MAX_DECISIONS:
                self._decisions.pop(0)
            self._proactive_suggestion_keys.add(key)
            self._proactive_suggestion_keys_fifo.append(key)
            while len(self._proactive_suggestion_keys_fifo) > MAX_PROACTIVE_SUGGESTION_KEYS:
                old_key = self._proactive_suggestion_keys_fifo.pop(0)
                self._proactive_suggestion_keys.discard(old_key)

    def reserve(
        self, resource_type: str, resource_id: str, joykey: str
    ) -> tuple[int, dict[str, Any]]:
        """
        占位：先 purge_expired；同 joykey 已有有效 hold -> 429；
        resource_id 已被占用 -> 409；否则创建 hold 并返回 200。
        返回 (status_code, payload)，payload 为 200 的 {hold_id, ttl_seconds}
        或 429/409 的 {error, message}（严格按 FIELD_REGISTRY）。
        """
        with self._lock:
            self.purge_expired()

            if joykey in self._joykey_to_hold_id:
                hold_id = self._joykey_to_hold_id[joykey]
                if hold_id in self._holds:
                    return 429, {
                        "error": ERROR_QUOTA_EXCEEDED,
                        "message": MESSAGE_QUOTA,
                    }
                self._joykey_to_hold_id.pop(joykey, None)

            if resource_id not in self._slots:
                return 409, {
                    "error": ERROR_RESOURCE_BUSY,
                    "message": MESSAGE_BUSY,
                }
            slot = self._slots[resource_id]
            if slot["slot_state"] != SLOT_STATE_FREE:
                now = time.time()
                self._record_proactive_busy_event_locked(resource_id, joykey, now)
                self._maybe_emit_proactive_delay_suggestions_locked(resource_id, now)
                return 409, {
                    "error": ERROR_RESOURCE_BUSY,
                    "message": MESSAGE_BUSY,
                }

            hold_id = f"hold_{uuid.uuid4().hex[:12]}"
            now = time.time()
            expires_at = now + self._ttl
            self._holds[hold_id] = {
                "charger_id": resource_id,
                "joykey": joykey,
                "expires_at": expires_at,
            }
            self._joykey_to_hold_id[joykey] = hold_id
            self._slots[resource_id] = {
                "slot_state": SLOT_STATE_HELD,
                "hold_id": hold_id,
                "joykey": joykey,
            }
            return 200, {"hold_id": hold_id, "ttl_seconds": self._ttl}

    def start_charging(self, hold_id: str, charger_id: str) -> None:
        """
        若 hold 存在且 charger_id 匹配，则将对应槽位设为 CHARGING；否则忽略。
        """
        with self._lock:
            self.purge_expired()
            rec = self._holds.get(hold_id)
            if not rec or rec["charger_id"] != charger_id:
                return
            if charger_id in self._slots:
                self._slots[charger_id]["slot_state"] = SLOT_STATE_CHARGING

    def stop_charging(self, hold_id: str, charger_id: str) -> None:
        """
        若 hold 存在且 charger_id 匹配，则释放 hold、槽位回 FREE，并清理 quota；否则忽略。
        """
        with self._lock:
            self.purge_expired()
            rec = self._holds.get(hold_id)
            if not rec or rec["charger_id"] != charger_id:
                return
            joykey = rec["joykey"]
            self._holds.pop(hold_id, None)
            self._joykey_to_hold_id.pop(joykey, None)
            if charger_id in self._slots:
                self._slots[charger_id] = {
                    "slot_state": SLOT_STATE_FREE,
                    "hold_id": None,
                    "joykey": None,
                }

    def snapshot(self) -> dict[str, Any]:
        """
        返回 /v1/snapshot 200 响应体，严格符合 FIELD_REGISTRY：
        { snapshot_at, chargers, holds, hazards, segment_passed_signals }。
        hazards 始终为 list（无数据为 []），项为 HazardSnapshot，字段/枚举与 FIELD_REGISTRY 一致；按 segment_id 排序。
        ChargerSlot: charger_id, slot_state (FREE/HELD/CHARGING), hold_id, joykey
        HoldSnapshot: hold_id, charger_id, joykey, expires_at + 扩展字段（默认 false/null）
        """
        with self._lock:
            self.purge_expired()
            now = time.time()
            self._process_due_soft_rechecks_locked(now)
            snapshot_at = _iso_utc(now)

            chargers: list[dict[str, Any]] = []
            for cid, slot in self._slots.items():
                chargers.append({
                    "charger_id": cid,
                    "slot_state": slot["slot_state"],
                    "hold_id": slot["hold_id"],
                    "joykey": slot["joykey"],
                })

            holds: list[dict[str, Any]] = []
            for hid, rec in self._holds.items():
                holds.append({
                    "hold_id": hid,
                    "charger_id": rec["charger_id"],
                    "joykey": rec["joykey"],
                    "expires_at": _iso_utc(rec["expires_at"]),
                    "is_priority_compensated": False,
                    "compensation_reason": None,
                    "queue_position_drift": None,
                    "incident_id": None,
                })
            chargers.sort(key=lambda c: c["charger_id"])
            holds.sort(key=lambda h: h["hold_id"])
            segment_passed_signals = _list_segment_passed_signals_locked(self, MAX_SEGMENT_PASSED)

            # M14.2 hazards：FIELD_REGISTRY HazardSnapshot；空为 []；同锁内读取；按 segment_id 排序；防脏值 500
            def _safe_int(v: Any, default: int) -> int:
                if v is None:
                    return default
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return default

            def _safe_nonempty_str(v: Any) -> str | None:
                if v is None:
                    return None
                if not isinstance(v, str):
                    return None
                s = (v or "").strip()
                return s if s else None

            _recheck_default = _safe_int(POLICY_CONFIG.get("soft_hazard_recheck_interval_minutes"), 5)
            seg_ids: list[str] = []
            for k in self._hazards_by_segment.keys():
                if isinstance(k, str) and (k or "").strip():
                    seg_ids.append((k or "").strip())
            hazards_out: list[dict[str, Any]] = []
            for seg_id in sorted(seg_ids):
                raw = self._hazards_by_segment.get(seg_id)
                rec = raw if isinstance(raw, dict) else {}
                st_val = rec.get("hazard_status")
                st = (st_val.strip() if isinstance(st_val, str) else "") or ""
                if st in {"OPEN", "SOFT_BLOCKED", "HARD_BLOCKED"}:
                    hazard_status = st
                elif st == "BLOCKED":
                    hazard_status = "SOFT_BLOCKED"
                elif st == "CLEAR":
                    hazard_status = "OPEN"
                else:
                    hazard_status = "OPEN"
                if hazard_status == "OPEN":
                    hazard_lock_mode = None
                else:
                    lm_val = rec.get("hazard_lock_mode")
                    lm = (lm_val.strip() if isinstance(lm_val, str) else "") or ""
                    if lm in {"SOFT_RECHECK", "HARD_MANUAL"}:
                        hazard_lock_mode = lm
                    else:
                        hazard_lock_mode = "HARD_MANUAL" if hazard_status == "HARD_BLOCKED" else "SOFT_RECHECK"
                hazard_id = _safe_nonempty_str(rec.get("hazard_id")) or f"haz_{seg_id}"
                hazards_out.append({
                    "hazard_id": hazard_id,
                    "segment_id": seg_id,
                    "hazard_status": hazard_status,
                    "hazard_lock_mode": hazard_lock_mode,
                    "recheck_due_at": _safe_nonempty_str(rec.get("recheck_due_at")),
                    "recheck_interval_minutes": _safe_int(rec.get("recheck_interval_minutes"), _recheck_default),
                    "soft_recheck_consecutive_blocked": _safe_int(rec.get("soft_recheck_consecutive_blocked"), 0),
                    "incident_id": _safe_nonempty_str(rec.get("incident_id")),
                    "work_order_id": _safe_nonempty_str(rec.get("work_order_id")),
                })
            hazards = hazards_out  # 自审：hazards 为空必 []；hazard_status/hazard_lock_mode 仅合法枚举；无未登记字段

        return {
            "snapshot_at": snapshot_at,
            "chargers": chargers,
            "holds": holds,
            "hazards": hazards,
            "segment_passed_signals": segment_passed_signals,
        }

    def record_segment_passed(
        self,
        segment_id: str,
        event_ts: float,
        joykey: str,
        truth_input_source: str,
        fleet_id: str | None = None,
    ) -> None:
        """M10：记录走通过信号。仅当 event_ts >= 已有 last_passed_ts 才更新整条记录；event_ts < old_ts 时直接 return。超 200 条按最旧淘汰。不触碰 hazard_status。"""
        with self._lock:
            rec = self._segment_passed.get(segment_id)
            old_ts = rec.get("last_passed_ts", 0.0) if rec else 0.0
            if event_ts < old_ts:
                # 乱序：不更新任何字段（last_passed_at / joykey 保持原值）
                return
            new_ts = max(old_ts, event_ts)
            self._segment_passed[segment_id] = {
                "last_passed_ts": new_ts,
                "last_passed_at": _iso_utc(new_ts),
                "joykey": joykey,
                "truth_input_source": truth_input_source,
                "fleet_id": fleet_id,
            }
            # M12A-1：仅保存形如 cell_x_y 的 segment_id 到 _robot_tracks（ring buffer）
            if isinstance(segment_id, str) and segment_id.startswith("cell_") and "_" in segment_id[5:]:
                parts = segment_id[5:].split("_", 1)
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    track_list = self._robot_tracks.setdefault(joykey, [])
                    track_list.append(segment_id)
                    if len(track_list) > ROBOT_TRACKS_MAX:
                        track_list.pop(0)
            if len(self._segment_passed) > MAX_SEGMENT_PASSED:
                by_ts = sorted(
                    self._segment_passed.items(),
                    key=lambda x: x[1]["last_passed_ts"],
                )
                for sid, _ in by_ts[: len(self._segment_passed) - MAX_SEGMENT_PASSED]:
                    self._segment_passed.pop(sid, None)

    def record_segment_passed_telemetry(
        self,
        joykey: str,
        fleet_id: str | None,
        segment_ids: list[str],
        event_occurred_at: float | str,
        truth_input_source: str,
    ) -> None:
        """
        M14.3 证据输入端：将 telemetry 上报写入 _segment_passed；写完后按 segment_freshness_window_minutes 裁剪过旧项。
        """
        joykey = _norm_required_str("joykey", joykey, MAX_TELEMETRY_JOYKEY_LEN)
        fleet_id = _norm_optional_str("fleet_id", fleet_id, MAX_ID_LEN)
        if not isinstance(segment_ids, list) or len(segment_ids) < 1:
            raise ValueError("invalid segment_ids")
        if len(segment_ids) > 200:
            raise ValueError("too many segment_ids")
        segment_ids = [_norm_required_str("segment_id", sid, MAX_ID_LEN) for sid in segment_ids]
        if not isinstance(truth_input_source, str):
            raise ValueError("invalid truth_input_source")
        s_ts = truth_input_source.strip()
        if truth_input_source != s_ts or not s_ts or s_ts not in ALLOWED_TRUTH_INPUT_SOURCES:
            raise ValueError("invalid truth_input_source")
        truth_input_source = s_ts

        event_ts = _parse_event_occurred_at(event_occurred_at)
        now = time.time()
        if event_ts > now + ALLOWED_FUTURE_SKEW_SECONDS:
            raise ValueError("event_occurred_at too far in future")

        for seg in segment_ids:
            self.record_segment_passed(
                segment_id=seg,
                event_ts=event_ts,
                joykey=joykey,
                truth_input_source=truth_input_source,
                fleet_id=fleet_id,
            )
        with self._lock:
            window_min = POLICY_CONFIG.get("segment_freshness_window_minutes", 10)
            if not isinstance(window_min, int) or window_min <= 0:
                window_min = 10
            cutoff = now - minute_to_seconds(window_min)
            to_drop = [sid for sid, rec in self._segment_passed.items() if (rec.get("last_passed_ts") or 0) < cutoff]
            for sid in to_drop:
                self._segment_passed.pop(sid, None)

    def list_segment_passed_signals(self, limit: int = 200) -> list[dict[str, Any]]:
        """M10：返回 segment_passed 信号列表，按 segment_id 排序，截断到 limit。"""
        with self._lock:
            return _list_segment_passed_signals_locked(self, limit)

    def get_reputation(self, joykey: str) -> dict[str, Any] | None:
        """M16：返回单机器人画像副本；无该 joykey 返回 None（不自动创建）。"""
        with self._lock:
            rep = self._reputation_by_joykey.get(joykey)
            if rep is None:
                return None
            return dict(rep)

    def get_score_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """M16：返回计分事件列表副本，按时间倒序，截断到 limit（上限 500）。"""
        limit = max(0, min(500, limit))
        with self._lock:
            events = list(self._score_events)[::-1][:limit]
            return [dict(e) for e in events]

    def get_vendor_scores(self, fleet_id: str | None = None) -> list[dict[str, Any]]:
        """M16：返回厂商分列表副本；fleet_id 非空时只返回该厂商。"""
        with self._lock:
            if fleet_id is not None and (fleet_id or "").strip():
                f = fleet_id.strip()
                rec = self._vendor_scores.get(f)
                return [dict(rec)] if isinstance(rec, dict) else []
            items = sorted(self._vendor_scores.values(), key=lambda x: (x.get("fleet_id") or ""))
            return [dict(r) for r in items]

    def list_incidents(
        self,
        incident_id: str | None = None,
        incident_type: str | None = None,
        incident_status: str | None = None,
        charger_id: str | None = None,
        segment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        返回 /v1/incidents 的 IncidentItem 列表；来自 store，不暴露 created_at。
        加锁构建快照副本、可选过滤、稳定排序（created_at desc，tie-breaker incident_id desc），返回新列表。
        """
        incident_id = _norm_optional_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        incident_type = _norm_optional_str("incident_type", incident_type, MAX_INCIDENT_TYPE_LEN)
        incident_status = _norm_optional_str("incident_status", incident_status, MAX_ID_LEN)
        charger_id = _norm_optional_str("charger_id", charger_id, MAX_CHARGER_ID_LEN)
        segment_id = _norm_optional_str("segment_id", segment_id, MAX_ID_LEN)
        if incident_type is not None and incident_type not in ALLOWED_INCIDENT_TYPES:
            raise ValueError("invalid incident_type")
        if incident_status is not None and incident_status not in ALLOWED_INCIDENT_STATUSES:
            raise ValueError("invalid incident_status")
        with self._lock:
            now = time.time()
            prev_status_by_id = {
                rec.get("incident_id"): rec.get("incident_status")
                for rec in self._incidents
                if rec.get("incident_id")
            }
            apply_witness_sla_downgrade_locked(
                self._incidents,
                self._witness_by_incident,
                now,
                WITNESS_SLA_TIMEOUT_MINUTES,
            )
            for rec in self._incidents:
                iid = rec.get("incident_id")
                if not iid:
                    continue
                prev = prev_status_by_id.get(iid)
                curr = rec.get("incident_status")
                if prev != curr:
                    data = self._incident_public_view_locked(rec)
                    self._enqueue_webhook_event_locked(
                        "INCIDENT_STATUS_CHANGED",
                        "INCIDENT",
                        iid,
                        data,
                    )
            snapshot_records = build_incidents_snapshot(self._incidents)

        def match(rec: dict[str, Any]) -> bool:
            if incident_id is not None and rec.get("incident_id") != incident_id:
                return False
            if incident_type is not None and rec.get("incident_type") != incident_type:
                return False
            if incident_status is not None and rec.get("incident_status") != incident_status:
                return False
            if charger_id is not None and rec.get("charger_id") != charger_id:
                return False
            if segment_id is not None and rec.get("segment_id") != segment_id:
                return False
            return True

        filtered = [r for r in snapshot_records if match(r)]
        # 稳定排序：created_at desc，tie-breaker incident_id desc（字符串用 reverse）
        filtered.sort(key=lambda x: (x.get("created_at", 0.0), x.get("incident_id", "")), reverse=True)

        for rec in filtered:
            rec.pop("created_at", None)
            rec.pop("status_updated_at", None)

        return filtered

    def _apply_witness_sla_downgrade_locked(self, now: float) -> None:
        """
        witness SLA 超时触发降级：
        - OPEN -> UNDER_OBSERVATION
        - ESCALATED/UNDER_OBSERVATION 保持
        - RESOLVED/EVIDENCE_CONFIRMED 不触发
        同时 upsert ai_insights: VISION_AUDIT_REQUESTED
        必须在持有 self._lock 时调用。
        """
        apply_witness_sla_downgrade_locked(
            self._incidents,
            self._witness_by_incident,
            now,
            WITNESS_SLA_TIMEOUT_MINUTES,
        )

    def _cleanup_ai_jobs_locked(self, now: float) -> None:
        """
        M9.2.4: 清理已完成/失败的 AI Jobs（仅内存）。
        必须在持有 self._lock 时调用。
        """
        cleanup_ai_jobs_locked(
            self._ai_jobs,
            self._ai_job_queue,
            self._active_ai_job_by_incident,
            now,
            AI_JOB_RETENTION_SECONDS,
        )

    def _cleanup_incidents_locked(self, now: float) -> None:
        """写时清理：必须在持有 self._lock 时调用。阶段1 TTL 清理 RESOLVED；阶段2 硬上限 pop 最老 RESOLVED 或 pop(0)。"""
        cleanup_incidents_locked(
            self._incidents,
            self._witness_by_incident,
            now,
            MAX_INCIDENTS,
            TTL_RESOLVED_LOW_PRIORITY_SECONDS,
            TTL_RESOLVED_HIGH_PRIORITY_SECONDS,
            LOW_RETENTION_INCIDENT_TYPES,
        )

    def report_blocked_incident(
        self,
        charger_id: str,
        incident_type: str,
        snapshot_ref: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> str:
        """
        创建一条 blocked 类事件并 append 到 _incidents；incident_status 固定 OPEN。
        incident_type 必须在 ALLOWED_INCIDENT_TYPES，charger_id 必须在 self._slots，否则 raise ValueError。
        写前调用 _cleanup_incidents_locked 做 TTL 与硬上限清理。返回 incident_id。
        """
        charger_id = _norm_required_str("charger_id", charger_id, MAX_CHARGER_ID_LEN)
        incident_type = _norm_required_str("incident_type", incident_type, MAX_INCIDENT_TYPE_LEN)
        if incident_type not in ALLOWED_INCIDENT_TYPES:
            raise ValueError("invalid incident_type")
        snapshot_ref = _norm_optional_str("snapshot_ref", snapshot_ref, MAX_SNAPSHOT_REF_LEN)
        evidence_refs = _normalize_evidence_refs(evidence_refs)
        with self._lock:
            if charger_id not in self._slots:
                raise ValueError("invalid charger_id")
            now = time.time()
            incident_id = report_blocked_incident_locked(
                self._incidents,
                self._witness_by_incident,
                self._slots,
                charger_id,
                incident_type,
                snapshot_ref,
                evidence_refs,
                now,
                MAX_INCIDENTS,
                TTL_RESOLVED_LOW_PRIORITY_SECONDS,
                TTL_RESOLVED_HIGH_PRIORITY_SECONDS,
                LOW_RETENTION_INCIDENT_TYPES,
                _iso_utc,
            )
            rec = find_incident_by_id(self._incidents, incident_id)
            if rec:
                data = self._incident_public_view_locked(rec)
                self._enqueue_webhook_event_locked(
                    "INCIDENT_CREATED",
                    "INCIDENT",
                    incident_id,
                    data,
                )
            return incident_id

    def update_incident_status(self, incident_id: str, new_status: str) -> None:
        """
        更新事件状态；new_status 必须在 ALLOWED_INCIDENT_STATUSES，流转必须在 ALLOWED_INCIDENT_STATUS_TRANSITIONS。
        找不到 incident 则 raise KeyError；非法状态或非法流转 raise ValueError。
        """
        incident_id = _norm_required_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        if new_status not in ALLOWED_INCIDENT_STATUSES:
            raise ValueError(f"invalid incident_status: {new_status}")
        with self._lock:
            rec = find_incident_by_id(self._incidents, incident_id)
            if rec is None:
                raise KeyError(f"incident not found: {incident_id}")
            current = rec.get("incident_status")
            allowed = ALLOWED_INCIDENT_STATUS_TRANSITIONS.get(current, set())
            if new_status not in allowed:
                raise ValueError(f"invalid status transition: {current} -> {new_status}")
            now = time.time()
            rec["incident_status"] = new_status
            rec["status_updated_at"] = now
            if new_status != current:
                data = self._incident_public_view_locked(rec)
                self._enqueue_webhook_event_locked(
                    "INCIDENT_STATUS_CHANGED",
                    "INCIDENT",
                    incident_id,
                    data,
                )

    def create_vision_audit_job(
        self,
        incident_id: str,
        model_tier: str | None = None,
        snapshot_ref: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        M9.1: 创建视觉审计 job（内存态）；M12A-1 冻结 render_snapshot 于 job 内。
        M13.2: model_tier/snapshot_ref/evidence_refs 存 job 用于审计。
        找不到 incident -> KeyError。
        """
        incident_id = _norm_required_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        snapshot_ref = _norm_optional_str("snapshot_ref", snapshot_ref, MAX_SNAPSHOT_REF_LEN)
        evidence_refs = _normalize_evidence_refs(evidence_refs)
        with self._lock:
            now = time.time()
            self._cleanup_ai_jobs_locked(now)
            rec = find_incident_by_id(self._incidents, incident_id)
            if rec is None:
                raise KeyError(f"incident not found: {incident_id}")
            chargers_layout = list(self._slots.keys())
            robot_tracks_copy = {
                k: list(v) for k, v in self._robot_tracks.items()
            }
            render_snapshot = {
                "incident_id": incident_id,
                "charger_id": rec.get("charger_id"),
                "chargers_layout": chargers_layout,
                "blocked_cell": rec.get("segment_id"),
                "robot_tracks": robot_tracks_copy,
                "created_at": _iso_utc(now),
            }
            return create_vision_audit_job_locked(
                self._incidents,
                self._ai_jobs,
                self._ai_job_queue,
                self._active_ai_job_by_incident,
                incident_id,
                now,
                render_snapshot=render_snapshot,
                model_tier=model_tier,
                snapshot_ref=snapshot_ref,
                evidence_refs=evidence_refs,
            )

    def create_dispatch_explain_job(
        self,
        hold_id: str,
        obstacle_type: str | None,
        audience: str,
        dispatch_reason_codes: list[str],
        context_ref: str | None,
        model_tier: str | None = None,
    ) -> dict[str, Any]:
        """M13.0：创建 dispatch_explain job；dispatch_reason_codes 校验由路由层做，此处假定合法。M13.2: model_tier 存 job。"""
        hold_id = _norm_required_str("hold_id", hold_id, MAX_ID_LEN)
        audience = _norm_required_str("audience", audience, MAX_ID_LEN)
        context_ref = _norm_optional_str("context_ref", context_ref, MAX_CONTEXT_REF_LEN)
        with self._lock:
            now = time.time()
            self._cleanup_ai_jobs_locked(now)
            return create_dispatch_explain_job_locked(
                self._ai_jobs,
                self._ai_job_queue,
                hold_id=hold_id,
                obstacle_type=obstacle_type,
                audience=audience,
                dispatch_reason_codes=dispatch_reason_codes or [],
                context_ref=context_ref,
                now=now,
                model_tier=model_tier,
            )

    def create_policy_suggest_job(
        self,
        incident_id: str | None,
        context_ref: str | None,
        model_tier: str | None = None,
    ) -> dict[str, Any]:
        """M13.1：创建 policy_suggest job；evidence_only，不接收 prompt/text/instruction。M13.2: model_tier 存 job。"""
        incident_id = _norm_optional_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        context_ref = _norm_optional_str("context_ref", context_ref, MAX_CONTEXT_REF_LEN)
        with self._lock:
            now = time.time()
            self._cleanup_ai_jobs_locked(now)
            return create_policy_suggest_job_locked(
                self._ai_jobs,
                self._ai_job_queue,
                incident_id=incident_id,
                context_ref=context_ref,
                now=now,
                model_tier=model_tier,
            )

    def apply_policy_suggestion_ledger_only(self, ai_report_id: str) -> dict[str, Any]:
        """M13.1：仅写 ledger 一条 POLICY_APPLIED，不改 incident/hazard/hold。返回 {status}。"""
        with self._lock:
            now = time.time()
            decision_id = f"dec_{uuid.uuid4().hex[:12]}"
            raw_summary = "admin confirmed apply_policy_suggestion (no state change in demo)"
            self._decisions.append({
                "decision_id": decision_id,
                "decision_type": "POLICY_APPLIED",
                "decision_basis": "HUMAN",
                "incident_id": None,
                "hold_id": None,
                "charger_id": None,
                "segment_id": None,
                "ai_report_id": ai_report_id,
                "evidence_refs": None,
                "summary": _cap_summary(raw_summary),
                "prev_bundle_hash": None,
                "bundle_hash": None,
                "created_at": now,
            })
            return {"status": "ACCEPTED"}

    def tick_ai_jobs(self, max_jobs: int) -> dict[str, int]:
        """
        M9.1 / M12A-1: 两段式推进 AI Jobs。锁内仅收集 tasks；锁外渲染 + provider；锁内回写。
        超 budget 不调 provider，写回 skipped due to budget，不升级 EVIDENCE_CONFIRMED。
        返回 {processed, completed}。
        """
        if not isinstance(max_jobs, int):
            try:
                max_jobs = int(max_jobs)
            except (ValueError, TypeError):
                max_jobs = 0
        limit = max_jobs if max_jobs > 0 else 0
        processed = 0
        tasks: list[dict] = []
        with self._lock:
            now = time.time()
            self._cleanup_ai_jobs_locked(now)
            elapsed = now - self._boot_ts
            if elapsed < 0:
                elapsed = 0
            day_sec = AI_BUDGET_DAY_SECONDS if isinstance(AI_BUDGET_DAY_SECONDS, int) and AI_BUDGET_DAY_SECONDS > 0 else 300
            bucket = int(elapsed // day_sec)
            bucket_key = f"demo_{bucket}"
            if self._ai_daily_calls_date != bucket_key:
                self._ai_daily_calls_date = bucket_key
                self._ai_daily_calls_count = 0
            processed, tasks = tick_ai_jobs_locked(
                self._incidents,
                self._ai_jobs,
                self._ai_job_queue,
                self._active_ai_job_by_incident,
                limit,
                now,
            )
            for t in tasks:
                if t.get("use_budget") and self._ai_daily_calls_count < JOYGATE_AI_DAILY_BUDGET_CALLS:
                    self._ai_daily_calls_count += 1
                    t["use_budget"] = True
                else:
                    t["use_budget"] = False

        provider = (os.getenv("JOYGATE_AI_PROVIDER") or "mock").strip().lower() or "mock"
        completed = 0
        results_by_job: dict[str, dict] = {}
        for t in tasks:
            if t.get("ai_job_type") in (AI_JOB_TYPE_DISPATCH_EXPLAIN, AI_JOB_TYPE_POLICY_SUGGEST):
                continue
            job_id = t.get("job_id")
            incident_id = t.get("incident_id")
            ai_report_id = t.get("ai_report_id")
            render_snapshot = t.get("render_snapshot") or {}
            incident_rec = t.get("incident_rec") or {}
            use_budget = t.get("use_budget") is True
            png_bytes = b""
            try:
                png_bytes = render_sim_snapshot_png(render_snapshot)
            except Exception as e:
                results_by_job[job_id] = {
                    "summary": f"render error: {e!s}",
                    "confidence": None,
                    "obstacle_type": None,
                    "sample_index": None,
                    "_job_failed": True,
                }
                completed += 1
                continue
            if use_budget:
                try:
                    res = generate_vision_audit_result(provider, incident_rec, png_bytes)
                    results_by_job[job_id] = res
                except Exception as e:
                    results_by_job[job_id] = {
                        "summary": f"provider error: {e!s}",
                        "confidence": None,
                        "obstacle_type": None,
                        "sample_index": None,
                        "_job_failed": True,
                    }
            else:
                results_by_job[job_id] = {
                    "summary": "skipped due to budget",
                    "confidence": None,
                    "obstacle_type": None,
                    "sample_index": None,
                }
            completed += 1

        with self._lock:
            now = time.time()
            for t in tasks:
                job_id = t.get("job_id")
                incident_id = t.get("incident_id")
                ai_report_id = t.get("ai_report_id")
                if t.get("ai_job_type") == AI_JOB_TYPE_DISPATCH_EXPLAIN:
                    job = self._ai_jobs.get(job_id)
                    if not isinstance(job, dict) or job.get("ai_job_status") != "IN_PROGRESS":
                        continue
                    if t.get("lease_until") is not None and job.get("lease_until") != t.get("lease_until"):
                        continue
                    hold_id = t.get("hold_id") or ""
                    charger_id = None
                    if hold_id and hold_id in self._holds:
                        charger_id = self._holds[hold_id].get("charger_id")
                    incident_id_from_charger = None
                    if charger_id:
                        for r in self._incidents:
                            if r.get("charger_id") == charger_id and r.get("incident_status") == "OPEN":
                                incident_id_from_charger = r.get("incident_id")
                                break
                    context_ref = t.get("context_ref")
                    context_ref_hash = ""
                    if isinstance(context_ref, str) and context_ref:
                        context_ref_hash = hashlib.sha256(context_ref.encode("utf-8")).hexdigest()[:12]
                    parts = [
                        f"hold_id={hold_id}",
                        f"audience={t.get('audience') or ''}",
                        f"dispatch_reason_codes={','.join(t.get('dispatch_reason_codes') or [])}",
                        f"obstacle_type={t.get('obstacle_type') or ''}",
                    ]
                    if charger_id:
                        parts.append(f"charger_id={charger_id}")
                    if incident_id_from_charger:
                        parts.append(f"incident_id={incident_id_from_charger}")
                    if context_ref_hash:
                        parts.append(f"context_ref_hash={context_ref_hash}")
                    summary = _cap_summary("; ".join(parts))
                    decision_id = f"dec_{uuid.uuid4().hex[:12]}"
                    self._decisions.append({
                        "decision_id": decision_id,
                        "decision_type": "REROUTE_SUGGESTED",
                        "decision_basis": "POLICY",
                        "incident_id": incident_id_from_charger,
                        "hold_id": hold_id,
                        "charger_id": charger_id,
                        "segment_id": None,
                        "ai_report_id": ai_report_id,
                        "evidence_refs": None,
                        "summary": summary,
                        "prev_bundle_hash": None,
                        "bundle_hash": None,
                        "created_at": now,
                    })
                    job["ai_job_status"] = "COMPLETED"
                    job["completed_at"] = now
                    job.pop("lease_until", None)
                    completed += 1
                    self._enqueue_webhook_event_locked(
                        "AI_JOB_STATUS_CHANGED",
                        "AI_JOB",
                        job_id,
                        {
                            "ai_job_id": job.get("ai_job_id"),
                            "ai_job_type": job.get("ai_job_type"),
                            "ai_job_status": "COMPLETED",
                            "incident_id": None,
                            "ai_report_id": ai_report_id,
                        },
                    )
                    continue
                if t.get("ai_job_type") == AI_JOB_TYPE_POLICY_SUGGEST:
                    job = self._ai_jobs.get(job_id)
                    if not isinstance(job, dict) or job.get("ai_job_status") != "IN_PROGRESS":
                        continue
                    if t.get("lease_until") is not None and job.get("lease_until") != t.get("lease_until"):
                        continue
                    incident_id_ps = t.get("incident_id")
                    context_ref_sha256 = t.get("context_ref_sha256") or ""
                    context_ref_hash = (context_ref_sha256[:12] if isinstance(context_ref_sha256, str) and len(context_ref_sha256) >= 12 else "")
                    parts_ps = [f"incident_id={incident_id_ps or ''}", f"context_ref_sha256={context_ref_sha256}"]
                    if context_ref_hash:
                        parts_ps.append(f"context_ref_hash={context_ref_hash}")
                    rec_ps = find_incident_by_id(self._incidents, incident_id_ps) if incident_id_ps else None
                    if rec_ps:
                        parts_ps.append(f"incident_status={rec_ps.get('incident_status') or ''}")
                    summary_ps = _cap_summary("; ".join(parts_ps))
                    decision_id_ps = f"dec_{uuid.uuid4().hex[:12]}"
                    self._decisions.append({
                        "decision_id": decision_id_ps,
                        "decision_type": "POLICY_SUGGESTED",
                        "decision_basis": "POLICY",
                        "incident_id": incident_id_ps,
                        "hold_id": None,
                        "charger_id": rec_ps.get("charger_id") if rec_ps else None,
                        "segment_id": rec_ps.get("segment_id") if rec_ps else None,
                        "ai_report_id": ai_report_id,
                        "evidence_refs": None,
                        "summary": summary_ps,
                        "prev_bundle_hash": None,
                        "bundle_hash": None,
                        "created_at": now,
                    })
                    job["ai_job_status"] = "COMPLETED"
                    job["completed_at"] = now
                    job.pop("lease_until", None)
                    completed += 1
                    self._enqueue_webhook_event_locked(
                        "AI_JOB_STATUS_CHANGED",
                        "AI_JOB",
                        job_id,
                        {
                            "ai_job_id": job.get("ai_job_id"),
                            "ai_job_type": job.get("ai_job_type"),
                            "ai_job_status": "COMPLETED",
                            "incident_id": incident_id_ps,
                            "ai_report_id": ai_report_id,
                        },
                    )
                    continue
                result = results_by_job.get(job_id)
                if result is None:
                    continue
                job = self._ai_jobs.get(job_id)
                if not isinstance(job, dict):
                    continue
                expected_lease_until = t.get("lease_until")
                # 只允许回写仍然由“本次领取 lease”持有的 IN_PROGRESS job
                if job.get("ai_job_status") != "IN_PROGRESS":
                    continue
                if expected_lease_until is not None and job.get("lease_until") != expected_lease_until:
                    continue
                job_status = "FAILED" if result.get("_job_failed") else "COMPLETED"
                job["ai_job_status"] = job_status
                job["completed_at"] = now
                job.pop("lease_until", None)
                if incident_id:
                    self._active_ai_job_by_incident.pop(incident_id, None)
                self._enqueue_webhook_event_locked(
                    "AI_JOB_STATUS_CHANGED",
                    "AI_JOB",
                    job_id,
                    {
                        "ai_job_id": job.get("ai_job_id"),
                        "ai_job_type": job.get("ai_job_type"),
                        "ai_job_status": job_status,
                        "incident_id": incident_id,
                        "ai_report_id": ai_report_id,
                    },
                )
                rec = find_incident_by_id(self._incidents, incident_id)
                if not rec:
                    continue
                upsert_ai_insight(
                    rec,
                    {
                        "insight_type": "VISION_AUDIT_REQUESTED",
                        "summary": "vision audit requested",
                        "confidence": None,
                        "obstacle_type": None,
                        "sample_index": None,
                        "ai_report_id": ai_report_id,
                    },
                )
                upsert_ai_insight(
                    rec,
                    {
                        "insight_type": "VISION_AUDIT_RESULT",
                        "summary": result.get("summary"),
                        "confidence": result.get("confidence"),
                        "obstacle_type": result.get("obstacle_type"),
                        "sample_index": result.get("sample_index"),
                        "ai_report_id": ai_report_id,
                    },
                )
                conf = result.get("confidence")
                if conf is not None and rec.get("incident_status") not in ("RESOLVED", "EVIDENCE_CONFIRMED"):
                    allowed = ALLOWED_INCIDENT_STATUS_TRANSITIONS.get(rec.get("incident_status"), set())
                    if "EVIDENCE_CONFIRMED" in allowed:
                        rec["incident_status"] = "EVIDENCE_CONFIRMED"
                        rec["status_updated_at"] = now
                        data = self._incident_public_view_locked(rec)
                        self._enqueue_webhook_event_locked(
                            "INCIDENT_STATUS_CHANGED",
                            "INCIDENT",
                            incident_id,
                            data,
                        )

        return {"processed": processed, "completed": completed}

    def list_ai_jobs(self) -> list[dict[str, Any]]:
        """M9.1: 返回 AI Jobs 列表（稳定顺序）。"""
        with self._lock:
            return list_ai_jobs_locked(self._ai_jobs)

    def create_webhook_subscription(
        self,
        target_url: str,
        event_types: list[str],
        secret: str | None,
        is_enabled: bool | None,
    ) -> dict[str, Any]:
        target_url = (target_url or "").strip()
        if not target_url:
            raise ValueError("invalid target_url")
        ok, _ = validate_webhook_target_url(
            target_url,
            allow_http=JOYGATE_WEBHOOK_ALLOW_HTTP,
            allow_localhost=JOYGATE_WEBHOOK_ALLOW_LOCALHOST,
        )
        if not ok:
            raise ValueError("invalid target_url")
        if not isinstance(event_types, list) or not event_types:
            raise ValueError("invalid event_types")
        normalized_types: list[str] = []
        seen: set[str] = set()
        for et in event_types:
            if not isinstance(et, str):
                raise ValueError("invalid event_type")
            et_norm = et.strip()
            if not et_norm:
                raise ValueError("invalid event_type")
            if et_norm in seen:
                continue
            seen.add(et_norm)
            normalized_types.append(et_norm)
        for et in normalized_types:
            if et not in ALLOWED_WEBHOOK_EVENT_TYPES:
                raise ValueError(f"invalid event_type: {et}")
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                secret = None
        elif secret is not None:
            raise ValueError("invalid secret")
        enabled = True if is_enabled is None else bool(is_enabled)
        with self._lock:
            # 上限：enabled 且 target_url 合法的订阅数 >= 50 则拒绝新建
            enabled_count = 0
            for rec in self._webhook_subscriptions.values():
                if not isinstance(rec, dict) or not rec.get("is_enabled"):
                    continue
                u = rec.get("target_url")
                if isinstance(u, str) and (u or "").strip():
                    enabled_count += 1
            if enabled_count >= MAX_WEBHOOK_SUBSCRIPTIONS:
                raise ValueError("too many webhook subscriptions")
            sub_id = f"sub_{uuid.uuid4().hex[:12]}"
            created_at = _iso_utc(time.time())
            rec = {
                "subscription_id": sub_id,
                "target_url": target_url,
                "event_types": list(normalized_types),
                "is_enabled": enabled,
                "created_at": created_at,
                "secret": secret,
            }
            self._webhook_subscriptions[sub_id] = rec
            return {
                "subscription_id": rec.get("subscription_id"),
                "target_url": rec.get("target_url"),
                "event_types": list(rec.get("event_types") or []),
                "is_enabled": rec.get("is_enabled"),
                "created_at": rec.get("created_at"),
            }

    def list_webhook_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            results: list[dict[str, Any]] = []
            for rec in self._webhook_subscriptions.values():
                if not isinstance(rec, dict):
                    continue
                results.append(
                    {
                        "subscription_id": rec.get("subscription_id"),
                        "target_url": rec.get("target_url"),
                        "event_types": list(rec.get("event_types") or []),
                        "is_enabled": rec.get("is_enabled"),
                        "created_at": rec.get("created_at"),
                    }
                )
            results.sort(key=lambda x: x.get("subscription_id") or "")
            return results

    def list_enabled_webhook_targets_for_event(self, event_type: str) -> list[dict[str, Any]]:
        if not isinstance(event_type, str) or not event_type.strip():
            return []
        with self._lock:
            targets: list[dict[str, Any]] = []
            for rec in self._webhook_subscriptions.values():
                if not isinstance(rec, dict):
                    continue
                if not rec.get("is_enabled"):
                    continue
                event_types = rec.get("event_types")
                if not isinstance(event_types, list):
                    continue
                if event_type not in event_types:
                    continue
                target_url = rec.get("target_url")
                if not isinstance(target_url, str) or not target_url.strip():
                    continue
                targets.append(
                    {
                        "subscription_id": rec.get("subscription_id"),
                        "target_url": target_url,
                        "secret": rec.get("secret"),
                    }
                )
            return targets

    def _incident_public_view_locked(self, rec: dict[str, Any]) -> dict[str, Any]:
        evidence_refs = rec.get("evidence_refs")
        if isinstance(evidence_refs, list):
            evidence_out = list(evidence_refs)[:5]
        else:
            evidence_out = None
        ai_insights = rec.get("ai_insights")
        if isinstance(ai_insights, list):
            insights_out = [dict(item) if isinstance(item, dict) else item for item in ai_insights]
        else:
            insights_out = ai_insights
        return {
            "incident_id": rec.get("incident_id"),
            "incident_type": rec.get("incident_type"),
            "incident_status": rec.get("incident_status"),
            "charger_id": rec.get("charger_id"),
            "segment_id": rec.get("segment_id"),
            "snapshot_ref": rec.get("snapshot_ref"),
            "evidence_refs": evidence_out,
            "ai_insights": insights_out,
        }

    def _enqueue_webhook_event_locked(
        self,
        event_type: str,
        object_type: str,
        object_id: str,
        data: dict[str, Any],
    ) -> None:
        if event_type not in ALLOWED_WEBHOOK_EVENT_TYPES:
            return
        payload = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "occurred_at": _iso_utc(time.time()),
            "object_type": object_type,
            "object_id": object_id,
            "data": data,
        }
        self._webhook_outbox.append(payload)
        if len(self._webhook_outbox) > MAX_WEBHOOK_OUTBOX:
            overflow = len(self._webhook_outbox) - MAX_WEBHOOK_OUTBOX
            if overflow > 0:
                del self._webhook_outbox[:overflow]

    def _cleanup_webhook_deliveries_locked(self, now: float) -> None:
        retention = WEBHOOK_DELIVERY_RETENTION_SECONDS
        if retention <= 0:
            return
        keep: list[dict[str, Any]] = []
        for item in self._webhook_deliveries:
            if not isinstance(item, dict):
                continue
            base_raw = item.get("updated_at") or item.get("created_at")
            if not base_raw:
                keep.append(item)
                continue
            try:
                base_ts = datetime.strptime(base_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, TypeError):
                keep.append(item)
                continue
            if (now - float(base_ts)) <= retention:
                keep.append(item)
        self._webhook_deliveries = keep

    def _has_webhook_delivery_locked(self, event_id: str, subscription_id: str) -> bool:
        """仅内部使用，须在锁内调用。若已存在相同 event_id+subscription_id 的 delivery 则返回 True。"""
        for item in self._webhook_deliveries:
            if not isinstance(item, dict):
                continue
            if item.get("event_id") == event_id and item.get("subscription_id") == subscription_id:
                return True
        return False

    def _create_webhook_delivery_locked(self, event: dict[str, Any], subscription_id: str, target_url: str) -> str:
        delivery_id = f"del_{uuid.uuid4().hex[:12]}"
        now = time.time()
        rec = {
            "delivery_id": delivery_id,
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "subscription_id": subscription_id,
            "target_url": target_url,
            "delivery_status": "PENDING",
            "attempts": 0,
            "last_status_code": None,
            "last_error": None,
            "created_at": _iso_utc(now),
            "updated_at": _iso_utc(now),
            "delivered_at": None,
        }
        self._webhook_deliveries.append(rec)
        self._cleanup_webhook_deliveries_locked(now)
        return delivery_id

    def create_webhook_delivery(self, event: dict[str, Any], subscription_id: str, target_url: str) -> str:
        with self._lock:
            return self._create_webhook_delivery_locked(event, subscription_id, target_url)

    def create_webhook_delivery_if_absent(
        self, event: dict[str, Any], subscription_id: str, target_url: str
    ) -> str | None:
        """若已存在相同 event_id+subscription_id 的 delivery 则返回 None，否则创建并返回 delivery_id。"""
        event_id = event.get("event_id") if isinstance(event.get("event_id"), str) else None
        with self._lock:
            if event_id and self._has_webhook_delivery_locked(event_id, subscription_id):
                return None
            return self._create_webhook_delivery_locked(event, subscription_id, target_url)

    def process_webhook_delivery(
        self,
        delivery_id: str,
        target_url: str,
        secret: str | None,
        event: dict[str, Any],
        timeout: int,
        max_attempts: int,
        backoff: int,
    ) -> None:
        result = send_webhook_with_retry(
            target_url,
            secret,
            event,
            timeout,
            max_attempts if max_attempts >= 1 else 1,
            backoff,
            allow_http=JOYGATE_WEBHOOK_ALLOW_HTTP,
            allow_localhost=JOYGATE_WEBHOOK_ALLOW_LOCALHOST,
        )
        now = time.time()
        with self._lock:
            for item in self._webhook_deliveries:
                if not isinstance(item, dict):
                    continue
                if item.get("delivery_id") != delivery_id:
                    continue
                item["attempts"] = result.get("attempts")
                item["last_status_code"] = result.get("last_status_code")
                item["last_error"] = result.get("last_error")
                item["updated_at"] = _iso_utc(now)
                if result.get("delivered"):
                    item["delivery_status"] = "DELIVERED"
                    item["delivered_at"] = item.get("delivered_at") or _iso_utc(now)
                else:
                    item["delivery_status"] = "FAILED"
                    item["delivered_at"] = None
                break
            self._cleanup_webhook_deliveries_locked(now)

    def list_webhook_deliveries(self) -> list[dict[str, Any]]:
        with self._lock:
            now = time.time()
            self._cleanup_webhook_deliveries_locked(now)
            items = list(self._webhook_deliveries)
            items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
            results: list[dict[str, Any]] = []
            for item in items[:50]:
                if not isinstance(item, dict):
                    continue
                results.append(
                    {
                        "delivery_id": item.get("delivery_id"),
                        "event_id": item.get("event_id"),
                        "event_type": item.get("event_type"),
                        "subscription_id": item.get("subscription_id"),
                        "target_url": item.get("target_url"),
                        "delivery_status": item.get("delivery_status"),
                        "attempts": item.get("attempts"),
                        "last_status_code": item.get("last_status_code"),
                        "last_error": item.get("last_error"),
                        "created_at": item.get("created_at"),
                        "updated_at": item.get("updated_at"),
                        "delivered_at": item.get("delivered_at"),
                    }
                )
            return results

    def drain_webhook_outbox(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._webhook_outbox)
            self._webhook_outbox.clear()
            return items

    def put_back_webhook_outbox(self, events: list[dict[str, Any]]) -> None:
        """塞回未派发的 event，保持顺序（下次 drain 先取到）。内部用，不进 FIELD_REGISTRY。"""
        if not isinstance(events, list) or not events:
            return
        with self._lock:
            self._webhook_outbox = list(events) + self._webhook_outbox
            if len(self._webhook_outbox) > MAX_WEBHOOK_OUTBOX:
                self._webhook_outbox = self._webhook_outbox[:MAX_WEBHOOK_OUTBOX]

    def _ensure_rep_locked(self, joykey: str, now: float) -> dict[str, Any]:
        """M16：在 _lock 内确保 joykey 存在 reputation 记录，不存在则创建默认（robot_score=60, tier, vote_weight, risk_flag=NONE）。"""
        if joykey not in self._reputation_by_joykey:
            vendor = _get_vendor_for_joykey(joykey)
            self._reputation_by_joykey[joykey] = {
                "robot_score": NEUTRAL_ROBOT_SCORE,
                "robot_tier": _tier_for_score(NEUTRAL_ROBOT_SCORE),
                "vote_weight": NEUTRAL_ROBOT_SCORE / 100.0,
                "risk_flag": "NONE",
                "robot_score_updated_at": _iso_utc(now),
                "vendor": vendor,
            }
        return self._reputation_by_joykey[joykey]

    def _apply_score_event_locked(
        self,
        score_event_id: str,
        score_event_type: str,
        joykey: str,
        delta_points: int | float,
        incident_id: str | None,
        snapshot_ref: str | None,
        evidence_refs: list[str] | None,
        now: float,
    ) -> None:
        """M16：在 _lock 内应用一条计分事件（幂等；已存在 score_event_id 则 return）。"""
        if score_event_id in self._score_event_ids:
            return
        self._score_event_ids.add(score_event_id)
        rep = self._ensure_rep_locked(joykey, now)
        raw = rep.get("robot_score")
        before_score = int(raw) if raw is not None else NEUTRAL_ROBOT_SCORE
        before_score = _clamp_score(before_score)
        after_score = _clamp_score(before_score + float(delta_points))
        rep["robot_score"] = after_score
        rep["robot_tier"] = _tier_for_score(after_score)
        rep["vote_weight"] = after_score / 100.0
        rep["robot_score_updated_at"] = _iso_utc(now)
        event_record = {
            "score_event_id": score_event_id,
            "score_event_type": score_event_type,
            "score_delta": float(delta_points),
            "score_evidence_refs": list(evidence_refs) if evidence_refs else [],
            "score_incident_id": incident_id or "",
            "score_snapshot_ref": snapshot_ref or "",
            "joykey": joykey,
            "occurred_at": _iso_utc(now),
        }
        self._score_events.append(event_record)
        while len(self._score_events) > MAX_SCORE_EVENTS:
            old = self._score_events.pop(0)
            self._score_event_ids.discard(old.get("score_event_id") or "")
        vendor_robot_scores: dict[str, list[int]] = {}
        for jk, r in self._reputation_by_joykey.items():
            v = r.get("vendor") or _get_vendor_for_joykey(jk)
            if v is None:
                v = "unknown"
            if v not in vendor_robot_scores:
                vendor_robot_scores[v] = []
            vendor_robot_scores[v].append(_int_or_default(r.get("robot_score"), NEUTRAL_ROBOT_SCORE))
        for v, scores in vendor_robot_scores.items():
            avg = round(sum(scores) / len(scores)) if scores else NEUTRAL_ROBOT_SCORE
            ops = 60
            if v in self._vendor_scores and isinstance(self._vendor_scores[v].get("vendor_score_ops"), (int, float)):
                ops = int(self._vendor_scores[v]["vendor_score_ops"])
            total = round(0.5 * avg + 0.5 * ops)
            self._vendor_scores[v] = {
                "fleet_id": v,
                "vendor_score_robot_mapped": _clamp_score(avg),
                "vendor_score_ops": ops,
                "vendor_score_total": _clamp_score(total),
                "updated_at": _iso_utc(now),
            }

    def witness_respond(
        self,
        witness_joykey: str,
        incident_id: str,
        charger_id: str,
        charger_state: str,
        obstacle_type: str | None,
        evidence_refs: list[str] | None,
        points_event_id: str | None,
    ) -> None:
        """
        M8 witness 桩占用投票：同一 witness_joykey 对同一 incident 只能投一次；points_event_id 仅用于网络重放幂等。
        在 _lock 内：charger_state 校验、先按 witness_joykey 去重再按 points_event_id 去重，计票后合并 evidence_refs，
        upsert ai_insights WITNESS_TALLY，达阈值将 incident_status 推进为 EVIDENCE_CONFIRMED。
        M16：用 _reputation_by_joykey 的 robot_score 覆盖票权（joykey_to_points_runtime）；非 EVIDENCE_CONFIRMED→EVIDENCE_CONFIRMED 时记分。
        找不到 incident -> KeyError；charger_id 不一致或 charger_state 非法 -> ValueError；非白名单机器人 -> PermissionError。
        """
        incident_id = _norm_required_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        charger_id = _norm_required_str("charger_id", charger_id, MAX_CHARGER_ID_LEN)
        charger_state = _norm_required_str("charger_state", charger_state, MAX_ID_LEN)
        points_event_id = _norm_optional_str("points_event_id", points_event_id, MAX_POINTS_EVENT_ID_LEN)
        obstacle_type = _norm_optional_str("obstacle_type", obstacle_type, MAX_ID_LEN)
        evidence_refs = _normalize_evidence_refs(evidence_refs)
        witness_joykey = (witness_joykey or "").strip()
        if not witness_joykey or witness_joykey not in ALLOWED_WITNESS_JOYKEYS:
            raise PermissionError("witness not allowed")

        with self._lock:
            rec_before = find_incident_by_id(self._incidents, incident_id)
            if rec_before is None:
                raise KeyError(f"incident not found: {incident_id}")
            prev_status = rec_before.get("incident_status")
            joykey_to_points_runtime = dict(JOYKEY_TO_POINTS)
            for jk, rep in self._reputation_by_joykey.items():
                if isinstance(rep, dict) and jk in joykey_to_points_runtime:
                    joykey_to_points_runtime[jk] = _int_or_default(rep.get("robot_score"), NEUTRAL_ROBOT_SCORE)
            witness_respond_locked(
                self._incidents,
                self._witness_by_incident,
                incident_id,
                charger_id,
                charger_state,
                obstacle_type,
                evidence_refs,
                points_event_id,
                witness_joykey,
                {"FREE", "OCCUPIED", "UNKNOWN_OCCUPANCY"},
                JOYKEY_TO_VENDOR,
                joykey_to_points_runtime,
                WITNESS_VENDOR_DECAY_GAMMA,
                WITNESS_MIN_DISTINCT_VENDORS,
                WITNESS_SCORE_REQUIRED,
                WITNESS_SCORE_REQUIRED_SINGLE_VENDOR,
                WITNESS_MIN_DISTINCT_VENDORS_RISKY,
                WITNESS_SCORE_REQUIRED_RISKY,
                WITNESS_MIN_MARGIN_RISKY,
                WITNESS_CERTIFIED_POINTS_THRESHOLD,
                WITNESS_MIN_CERTIFIED_SUPPORT_RISKY,
            )
            rec_after = find_incident_by_id(self._incidents, incident_id)
            if rec_after is None:
                raise KeyError(f"incident not found: {incident_id}")
            new_status = rec_after.get("incident_status")
            now2 = time.time()
            if prev_status != "EVIDENCE_CONFIRMED" and new_status == "EVIDENCE_CONFIRMED":
                w = self._witness_by_incident.get(incident_id)
                seen = w.get("seen_witness_joykeys") if isinstance(w, dict) else None
                if isinstance(seen, set):
                    joykeys_to_score = list(seen)
                elif isinstance(seen, dict):
                    joykeys_to_score = list(seen.keys())
                elif isinstance(seen, list):
                    joykeys_to_score = list(seen)
                else:
                    joykeys_to_score = [witness_joykey]
                snapshot_ref = (rec_after.get("snapshot_ref") or "").strip() or None
                ev_refs_raw = rec_after.get("evidence_refs")
                ev_refs = _normalize_evidence_refs(ev_refs_raw if isinstance(ev_refs_raw, list) else None)
                for jk in joykeys_to_score:
                    if not jk or not isinstance(jk, str):
                        continue
                    if jk not in ALLOWED_WITNESS_JOYKEYS:
                        continue
                    raw = hashlib.sha256(f"m16:witness_verified:{incident_id}:{jk}".encode()).hexdigest()[:12]
                    score_event_id = f"se_{raw}"
                    self._apply_score_event_locked(
                        score_event_id,
                        "WITNESS_VOTE_VERIFIED",
                        jk,
                        SCORE_DELTA_WITNESS_VERIFIED,
                        incident_id,
                        snapshot_ref,
                        ev_refs,
                        now2,
                    )

    def _ensure_soft_hazard_locked(self, segment_id: str, now: float) -> dict[str, Any]:
        """
        M14.4 在 self._lock 内调用：将 segment 的 hazard 制度化為 SOFT（OPEN/overlay/BLOCKED/CLEAR/None → SOFT）；
        HARD_BLOCKED 不改动直接 return rec。原地更新 rec，不整段覆盖。
        """
        raw = POLICY_CONFIG.get("soft_hazard_recheck_interval_minutes", 5)
        try:
            interval = int(raw) if raw is not None else 5
        except (TypeError, ValueError):
            interval = 5
        if interval <= 0:
            interval = 5
        due_ts = now + minute_to_seconds(interval)
        recheck_due_at = _iso_utc(due_ts)

        rec = self._hazards_by_segment.get(segment_id)
        if not isinstance(rec, dict):
            rec = {}
        if rec.get("hazard_status") == "HARD_BLOCKED":
            return rec
        # SOFT_BLOCKED 已存在且 recheck_due_at 有效时，不往后顺延，避免刷票拖延复核
        if rec.get("hazard_status") == "SOFT_BLOCKED" and rec.get("hazard_lock_mode") == "SOFT_RECHECK":
            existing_due = rec.get("recheck_due_at")
            if _parse_recheck_due_at(existing_due if isinstance(existing_due, str) else "") is not None:
                recheck_due_at = existing_due
        rec["segment_id"] = segment_id
        rec["hazard_status"] = "SOFT_BLOCKED"
        rec["hazard_lock_mode"] = "SOFT_RECHECK"
        rec["recheck_due_at"] = recheck_due_at
        rec["recheck_interval_minutes"] = interval
        rec.setdefault("soft_recheck_consecutive_blocked", 0)
        rec.setdefault("incident_id", None)
        rec.setdefault("work_order_id", None)
        rec.setdefault("hazard_id", f"haz_{uuid.uuid4().hex[:12]}")
        self._hazards_by_segment[segment_id] = rec
        return rec

    def _recheck_verdict(self, segment_id: str, now: float) -> str:
        """
        在 self._lock 内调用：复核判定三态。
        返回 "PASSABLE" | "BLOCKED" | "INCONCLUSIVE"。
        Telemetry PASSABLE 优先：last_passed_ts 在 segment_freshness_window_minutes 内 => PASSABLE。
        否则 Witness 投票（ts 在 segment_witness_sla_timeout_minutes 内）：
        有效票 < required => INCONCLUSIVE；
        有效票 >= required：PASSABLE>BLOCKED => PASSABLE，BLOCKED>PASSABLE => BLOCKED，平票 => INCONCLUSIVE。
        BLOCKED 仅由 witness 多数票给出；telemetry 只提供 PASSABLE。
        """
        window_min = POLICY_CONFIG.get("segment_freshness_window_minutes", 10)
        if not isinstance(window_min, int) or window_min <= 0:
            window_min = 10
        telemetry_cutoff = now - minute_to_seconds(window_min)

        telemetry = self._segment_passed.get(segment_id)
        if isinstance(telemetry, dict):
            last_passed_ts = telemetry.get("last_passed_ts") or 0
            if last_passed_ts >= telemetry_cutoff:
                return "PASSABLE"

        witness_window_min = POLICY_CONFIG.get("segment_witness_sla_timeout_minutes", 1)
        if not isinstance(witness_window_min, (int, float)) or witness_window_min <= 0:
            witness_window_min = 1
        witness_cutoff = now - minute_to_seconds(witness_window_min)

        votes_required = POLICY_CONFIG.get("segment_witness_votes_required", 2)
        if not isinstance(votes_required, int) or votes_required <= 0:
            votes_required = 2
        passable_votes = 0
        blocked_votes = 0
        for e in self._segment_witness_events:
            if e.get("segment_id") != segment_id:
                continue
            ts = e.get("ts") or 0
            if ts < witness_cutoff:
                continue
            st = (e.get("segment_state") or "").strip()
            if st == "PASSABLE":
                passable_votes += 1
            elif st == "BLOCKED":
                blocked_votes += 1
        total = passable_votes + blocked_votes
        if total < votes_required:
            return "INCONCLUSIVE"
        if passable_votes > blocked_votes:
            return "PASSABLE"
        if blocked_votes > passable_votes:
            return "BLOCKED"
        return "INCONCLUSIVE"

    def _process_due_soft_rechecks_locked(self, now: float) -> None:
        """
        在 self._lock 内调用：只处理 hazard_status==SOFT_BLOCKED 且 recheck_due_at 合法且 due_ts<=now 的 hazard。
        M14.6：三态判定（PASSABLE/INCONCLUSIVE/BLOCKED）；INCONCLUSIVE 不增加 consecutive；BLOCKED 达阈值升级 HARD。
        """
        raw_threshold = POLICY_CONFIG.get("soft_hazard_escalate_after_rechecks", 2)
        try:
            threshold = int(raw_threshold) if raw_threshold is not None else 2
        except (TypeError, ValueError):
            threshold = 2
        if threshold <= 0:
            threshold = 2

        for segment_id, hazard in list(self._hazards_by_segment.items()):
            if not isinstance(hazard, dict) or hazard.get("hazard_status") != "SOFT_BLOCKED":
                continue
            recheck_due_at = hazard.get("recheck_due_at")
            due_ts = _parse_recheck_due_at(recheck_due_at if isinstance(recheck_due_at, str) else "")
            if due_ts is None or due_ts > now:
                continue

            verdict = self._recheck_verdict(segment_id, now)
            old_status = hazard.get("hazard_status")
            interval = hazard.get("recheck_interval_minutes", 5)
            if not isinstance(interval, (int, float)) or interval <= 0:
                interval = 5
            interval_sec = minute_to_seconds(interval)

            if verdict == "PASSABLE":
                hazard["hazard_status"] = "OPEN"
                hazard["hazard_lock_mode"] = None
                hazard["recheck_due_at"] = None
                hazard["soft_recheck_consecutive_blocked"] = 0
            elif verdict == "INCONCLUSIVE":
                hazard["recheck_due_at"] = _iso_utc(now + interval_sec)
                # 状态仍 SOFT_BLOCKED，不增加 soft_recheck_consecutive_blocked，不升级 HARD
            else:
                # BLOCKED
                raw_consecutive = hazard.get("soft_recheck_consecutive_blocked")
                try:
                    consecutive = int(raw_consecutive) if raw_consecutive is not None else 0
                except (ValueError, TypeError):
                    consecutive = 0
                if consecutive < 0:
                    consecutive = 0
                consecutive += 1
                hazard["soft_recheck_consecutive_blocked"] = consecutive
                if consecutive < threshold:
                    hazard["recheck_due_at"] = _iso_utc(now + interval_sec)
                else:
                    hazard["hazard_status"] = "HARD_BLOCKED"
                    hazard["hazard_lock_mode"] = "HARD_MANUAL"
                    hazard["recheck_due_at"] = None
                    if hazard.get("work_order_id"):
                        pass
                    else:
                        hazard["work_order_id"] = f"wo_{uuid.uuid4().hex[:12]}"

            self._hazards_by_segment[segment_id] = hazard
            if old_status != hazard.get("hazard_status"):
                self._enqueue_webhook_event_locked(
                    "HAZARD_STATUS_CHANGED",
                    "HAZARD",
                    segment_id,
                    {
                        "segment_id": segment_id,
                        "hazard_status": hazard.get("hazard_status"),
                        "obstacle_type": hazard.get("obstacle_type"),
                        "evidence_refs": hazard.get("evidence_refs"),
                    },
                )

    def process_due_soft_rechecks(self, now: float) -> None:
        """
        遍历所有 SOFT_BLOCKED 的 hazards，检查是否到期复核；
        根据 witness 和 telemetry 证据更新 hazard 状态（OPEN 或保持 SOFT_BLOCKED 并重排 due）。
        """
        with self._lock:
            self._process_due_soft_rechecks_locked(now)

    def record_segment_witness(
        self,
        segment_id: str,
        segment_state: str,
        witness_joykey: str,
        points_event_id: str | None = None,
        evidence_refs: list[str] | None = None,
        obstacle_type: str | None = None,
    ) -> None:
        """
        M14.3/M14.4 证据输入端：BLOCKED 调用 _ensure_soft_hazard_locked（制度化 SOFT）；PASSABLE 不创建 OPEN，仅更新证据或只写事件；UNKNOWN 只写事件。
        """
        witness_joykey = _norm_required_str("witness_joykey", witness_joykey, MAX_ID_LEN)
        if witness_joykey not in ALLOWED_WITNESS_JOYKEYS:
            raise PermissionError("witness not allowed")
        if segment_state not in ALLOWED_SEGMENT_STATES:
            raise ValueError(f"invalid segment_state: {segment_state!r}")
        segment_id = _norm_required_str("segment_id", segment_id, MAX_ID_LEN)
        points_event_id = _norm_optional_str("points_event_id", points_event_id, MAX_POINTS_EVENT_ID_LEN)
        obstacle_type = _norm_optional_str("obstacle_type", obstacle_type, MAX_ID_LEN)
        refs = _normalize_evidence_refs(evidence_refs)

        with self._lock:
            if segment_id not in self._witness_by_segment:
                self._witness_by_segment[segment_id] = {"seen_points_event_ids": {}}
            w = self._witness_by_segment[segment_id]
            if not isinstance(w.get("seen_points_event_ids"), dict):
                w["seen_points_event_ids"] = {}
            now = time.time()
            updated_at = _iso_utc(now)
            if points_event_id and points_event_id in w["seen_points_event_ids"]:
                if segment_state == "BLOCKED":
                    rec = self._hazards_by_segment.get(segment_id) or {}
                    recheck_due_at_val = rec.get("recheck_due_at")
                    if not (recheck_due_at_val and isinstance(recheck_due_at_val, str) and (recheck_due_at_val or "").strip()):
                        rec = self._ensure_soft_hazard_locked(segment_id, now)
                        rec["updated_at"] = updated_at
                        self._hazards_by_segment[segment_id] = rec
                return
            if points_event_id:
                w["seen_points_event_ids"][points_event_id] = now
            window_min = POLICY_CONFIG.get("segment_freshness_window_minutes", 10)
            if not isinstance(window_min, int) or window_min <= 0:
                window_min = 10
            cutoff = now - minute_to_seconds(window_min)
            w["seen_points_event_ids"] = {eid: ts for eid, ts in w["seen_points_event_ids"].items() if ts >= cutoff}
            if len(w["seen_points_event_ids"]) > MAX_POINTS_EVENT_IDS_PER_SEGMENT:
                by_ts = sorted(w["seen_points_event_ids"].items(), key=lambda x: x[1])
                for eid, _ in by_ts[: len(w["seen_points_event_ids"]) - MAX_POINTS_EVENT_IDS_PER_SEGMENT]:
                    w["seen_points_event_ids"].pop(eid, None)
            old_rec = self._hazards_by_segment.get(segment_id) or {}
            old_status = old_rec.get("hazard_status")

            if segment_state == "BLOCKED":
                rec = self._ensure_soft_hazard_locked(segment_id, now)
                rec["obstacle_type"] = obstacle_type
                rec["evidence_refs"] = refs if refs else None
                rec["updated_at"] = updated_at
                self._hazards_by_segment[segment_id] = rec
            elif segment_state == "PASSABLE":
                if segment_id in self._hazards_by_segment:
                    rec = self._hazards_by_segment[segment_id]
                    # M15：HARD_BLOCKED 永不因 witness PASSABLE 解封；仅更新证据/时间，可写审计提醒
                    if rec.get("hazard_status") == "HARD_BLOCKED":
                        rec["obstacle_type"] = obstacle_type
                        rec["evidence_refs"] = refs if refs else None
                        rec["updated_at"] = updated_at
                        self._decisions.append({
                            "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
                            "decision_type": "WITNESS_RECHECK_REQUESTED",
                            "decision_basis": "WITNESS",
                            "incident_id": rec.get("incident_id"),
                            "hold_id": None,
                            "charger_id": None,
                            "segment_id": segment_id,
                            "ai_report_id": None,
                            "evidence_refs": refs,
                            "summary": _cap_summary(f"witness PASSABLE on HARD_BLOCKED segment {segment_id} (reminder only, no unblock)"),
                            "prev_bundle_hash": None,
                            "bundle_hash": None,
                            "created_at": now,
                        })
                    else:
                        rec["obstacle_type"] = obstacle_type
                        rec["evidence_refs"] = refs if refs else None
                        rec["updated_at"] = updated_at
                # 不存在 hazard 则不创建，只写 _segment_witness_events
            else:
                # UNKNOWN: 不写 hazard_status，只写 _segment_witness_events
                pass

            new_status = self._hazards_by_segment.get(segment_id, {}).get("hazard_status")
            if old_status != new_status:
                self._enqueue_webhook_event_locked(
                    "HAZARD_STATUS_CHANGED",
                    "HAZARD",
                    segment_id,
                    {
                        "segment_id": segment_id,
                        "hazard_status": new_status,
                        "obstacle_type": self._hazards_by_segment.get(segment_id, {}).get("obstacle_type"),
                        "evidence_refs": self._hazards_by_segment.get(segment_id, {}).get("evidence_refs"),
                    },
                )

            self._segment_witness_events.append({
                "segment_id": segment_id,
                "segment_state": segment_state,
                "witness_joykey": witness_joykey,
                "points_event_id": points_event_id,
                "evidence_refs": refs if refs else None,
                "ts": now,
            })
            # 按 segment_freshness_window_minutes 清理过旧项
            window_min = POLICY_CONFIG.get("segment_freshness_window_minutes", 10)
            if not isinstance(window_min, int) or window_min <= 0:
                window_min = 10
            cutoff = now - minute_to_seconds(window_min)
            self._segment_witness_events[:] = [e for e in self._segment_witness_events if (e.get("ts") or 0) >= cutoff]
            if len(self._segment_witness_events) > MAX_SEGMENT_WITNESS_EVENTS:
                self._segment_witness_events.sort(key=lambda e: e.get("ts") or 0)
                self._segment_witness_events[:] = self._segment_witness_events[-MAX_SEGMENT_WITNESS_EVENTS:]

    def segment_witness_respond(
        self,
        witness_joykey: str,
        segment_id: str,
        hazard_status: str,
        obstacle_type: str | None,
        evidence_refs: list[str] | None,
        points_event_id: str | None,
    ) -> None:
        """
        M9 兼容入口：hazard_status BLOCKED/CLEAR 映射为 segment_state，委托 record_segment_witness。
        """
        if hazard_status not in ALLOWED_HAZARD_STATUSES:
            raise ValueError(f"invalid hazard_status: {hazard_status!r}")
        segment_state = "BLOCKED" if hazard_status == "BLOCKED" else "PASSABLE"
        self.record_segment_witness(
            segment_id=segment_id,
            segment_state=segment_state,
            witness_joykey=witness_joykey,
            points_event_id=points_event_id,
            evidence_refs=evidence_refs,
            obstacle_type=obstacle_type,
        )

    def report_work_order(
        self,
        work_order_id: str,
        incident_id: str | None,
        segment_id: str | None,
        charger_id: str | None,
        work_order_status: str,
        event_occurred_at: float | str,
        evidence_refs: list[str] | None,
    ) -> None:
        """
        M15 工单闭环：唯一解封 HARD_BLOCKED 的入口。
        仅当 work_order_status==DONE 且 segment_id 非空时，若该 segment 当前为 HARD_BLOCKED 则解封为 OPEN（同锁内原子）。
        非 DONE 或 segment_id 为空：只更新/记录工单信息，不解封。
        """
        work_order_id = _norm_required_str("work_order_id", work_order_id, MAX_ID_LEN)
        if work_order_status not in ALLOWED_WORK_ORDER_STATUSES:
            raise ValueError("invalid work_order_status")
        segment_id = _norm_optional_str("segment_id", segment_id, MAX_ID_LEN)
        evidence_refs = _normalize_evidence_refs(evidence_refs)
        incident_id = _norm_optional_str("incident_id", incident_id, MAX_INCIDENT_ID_LEN)
        charger_id = _norm_optional_str("charger_id", charger_id, MAX_CHARGER_ID_LEN)
        event_ts = _parse_event_occurred_at(event_occurred_at)
        now_wo = time.time()
        if event_ts > now_wo + ALLOWED_FUTURE_SKEW_SECONDS:
            raise ValueError("event_occurred_at too far in future")

        with self._lock:
            if work_order_status != "DONE":
                return
            if not segment_id:
                return
            seg = segment_id
            hazard = self._hazards_by_segment.get(seg)
            if not isinstance(hazard, dict) or hazard.get("hazard_status") != "HARD_BLOCKED":
                return
            existing_wo = hazard.get("work_order_id")
            if isinstance(existing_wo, str) and (existing_wo or "").strip() and existing_wo != work_order_id:
                raise ValueError("invalid work_order_id")
            old_status = hazard.get("hazard_status")
            hazard["hazard_status"] = "OPEN"
            hazard["hazard_lock_mode"] = None
            hazard["recheck_due_at"] = None
            hazard["work_order_id"] = None
            hazard["soft_recheck_consecutive_blocked"] = 0
            self._hazards_by_segment[seg] = hazard
            if old_status != hazard.get("hazard_status"):
                self._enqueue_webhook_event_locked(
                    "HAZARD_STATUS_CHANGED",
                    "HAZARD",
                    seg,
                    {
                        "segment_id": seg,
                        "hazard_status": hazard.get("hazard_status"),
                        "obstacle_type": hazard.get("obstacle_type"),
                        "evidence_refs": hazard.get("evidence_refs"),
                    },
                )

    def list_hazards(self) -> list[dict[str, Any]]:
        """只读：返回 hazards 列表，按 segment_id 排序；hazard_status 为系统正式值 OPEN | SOFT_BLOCKED | HARD_BLOCKED（与 FIELD_REGISTRY /v1/hazards 一致）。"""
        with self._lock:
            items: list[dict[str, Any]] = []
            for seg_id, rec in self._hazards_by_segment.items():
                if not isinstance(rec, dict):
                    continue
                st = rec.get("hazard_status")
                if st not in ("OPEN", "SOFT_BLOCKED", "HARD_BLOCKED"):
                    continue
                segment_id = seg_id if isinstance(seg_id, str) and (seg_id or "").strip() else rec.get("segment_id")
                if not segment_id or not isinstance(segment_id, str) or not (segment_id or "").strip():
                    continue
                segment_id = (segment_id or "").strip()
                updated_at = rec.get("updated_at")
                if not updated_at or not isinstance(updated_at, str) or not (updated_at or "").strip():
                    continue
                items.append({
                    "segment_id": segment_id,
                    "hazard_status": st,
                    "obstacle_type": rec.get("obstacle_type"),
                    "evidence_refs": rec.get("evidence_refs"),
                    "updated_at": (updated_at or "").strip(),
                })
            items.sort(key=lambda x: (x.get("segment_id") or ""))
            return items

    def incidents_daily_report(self, tz_name: str = "Asia/Taipei") -> dict[str, Any]:
        """
        只读：供 dashboard 使用的“今日” incidents 汇总（支持 DEMO/CALENDAR 两种模式）。
        
        NOTE: tz_name 仅为历史兼容保留；当前“今日统计”由 JOYGATE_DASHBOARD_DAY_MODE（DEMO/CALENDAR）决定。
        
        并发安全：锁内拷贝、锁外计算，不遍历时 mutate。不改变 list_incidents 对外行为。
        返回 dict：today_date, total, severe, resolved, unresolved, by_type, by_status, severe_items, stale_unresolved，
        以及 day_mode/demo_day_seconds/demo_day_index/tz_offset_hours（仅供 HTML 展示，不影响 /v1）。

        今日口径：
        - unresolved：全量未解决（incident_status != "RESOLVED"，不看日期）
        - DEMO 模式（默认）：以 self._boot_ts 为 0 时刻，DEMO_DAY_SECONDS 秒为 1 天，计算 demo_day_index；
          resolved_today 为当前 demo day 内变为 RESOLVED 的事件。
        - CALENDAR 模式（后门）：采用 DASHBOARD_TZ_OFFSET_HOURS 相对 UTC 的时区，将 status_updated_at/created_at 映射到日历日期；
          resolved_today 为“该时区今天”内变为 RESOLVED 的事件。

        severe：unresolved 中 incident_status in SEVERE_INCIDENT_STATUSES 的数量。
        stale_unresolved：unresolved 中 base_ts=status_updated_at/created_at 超过 INCIDENT_STALE_MINUTES*60 的数量（真实分钟，不随 DEMO 缩放）。
        口径对照：incident_type/incident_status 与 FIELD_REGISTRY 一致；/v1.incidents 仍 8 字段，不泄露 created_at/status_updated_at。
        """
        with self._lock:
            copy_list: list[dict[str, Any]] = []
            for rec in self._incidents:
                copy_list.append({
                    "incident_id": rec.get("incident_id"),
                    "incident_type": rec.get("incident_type"),
                    "incident_status": rec.get("incident_status"),
                    "charger_id": rec.get("charger_id"),
                    "segment_id": rec.get("segment_id"),
                    "created_at": rec.get("created_at", 0.0),
                    "status_updated_at": rec.get("status_updated_at"),
                })

        return build_incidents_daily_report(
            copy_list,
            time.time(),
            self._boot_ts,
            DASHBOARD_DAY_MODE,
            DEMO_DAY_SECONDS,
            DASHBOARD_TZ_OFFSET_HOURS,
            INCIDENT_STALE_MINUTES,
            SEVERE_INCIDENT_STATUSES,
            _date_str_with_offset,
        )
