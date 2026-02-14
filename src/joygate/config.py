from __future__ import annotations

import json
import os
from pathlib import Path
from types import MappingProxyType

_ENV_LOADED = False


def _load_env_file() -> None:
    """从仓库根 .env（或 JOYGATE_ENV_FILE）加载环境变量；仅 setdefault，不覆盖已有。只执行一次。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = os.environ.get("JOYGATE_ENV_FILE")
    if env_path:
        path = Path(env_path)
    else:
        repo_root = Path(__file__).resolve().parents[2]
        path = repo_root / ".env"
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key.startswith("#"):
            continue
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    """读取环境变量并转为 int；None/空字符串/转换失败时返回 default（不打印日志）。"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    """读取环境变量并转为 float；None/空字符串/转换失败时返回 default（不打印日志）。"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """安全解析布尔环境变量：接受 "1/true/yes/on" 为 True"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    raw_lower = raw.lower().strip()
    return raw_lower in ("1", "true", "yes", "on")


_load_env_file()

# --- sandbox 环境变量（内部，不进 FIELD_REGISTRY）---
MAX_SANDBOXES = _env_int("JOYGATE_MAX_SANDBOXES", 200)
SANDBOX_IDLE_TTL_SECONDS = _env_int("JOYGATE_SANDBOX_IDLE_TTL_SECONDS", 3600)
RATE_LIMIT_PER_SANDBOX_PER_MIN = _env_int("JOYGATE_RATE_LIMIT_PER_SANDBOX_PER_MIN", 120)
RATE_LIMIT_PER_IP_PER_MIN = _env_int("JOYGATE_RATE_LIMIT_PER_IP_PER_MIN", 300)
ALLOW_SANDBOX_HEADER = _env_bool("JOYGATE_ALLOW_SANDBOX_HEADER", False)
REQUIRE_SINGLE_WORKER = _env_bool("JOYGATE_REQUIRE_SINGLE_WORKER", True)


# --- incidents 写时清理与硬上限（demo 默认，环境变量可覆盖，不对外公开）---
MAX_INCIDENTS = _env_int("JOYGATE_MAX_INCIDENTS", 200)
TTL_RESOLVED_LOW_PRIORITY_SECONDS = _env_int("JOYGATE_TTL_RESOLVED_LOW_SECONDS", 300)
TTL_RESOLVED_HIGH_PRIORITY_SECONDS = _env_int("JOYGATE_TTL_RESOLVED_HIGH_SECONDS", 86400)

# 管理员 stale 提醒阈值（分钟，环境变量可覆盖）
INCIDENT_STALE_MINUTES = _env_int("JOYGATE_INCIDENT_STALE_MINUTES", 30)


# --- witness 相关 env（内部配置，不进 FIELD_REGISTRY）---
# 防呆：最小为 2，避免配置错误导致阈值过低
WITNESS_VOTES_REQUIRED = max(_env_int("JOYGATE_WITNESS_VOTES_REQUIRED", 2), 2)

_raw_gamma = _env_float("JOYGATE_WITNESS_VENDOR_DECAY_GAMMA", 0.5)
WITNESS_VENDOR_DECAY_GAMMA = _raw_gamma if 0 < _raw_gamma <= 1 else 0.5
WITNESS_SCORE_REQUIRED = _env_float("JOYGATE_WITNESS_SCORE_REQUIRED", 2.0)
WITNESS_SCORE_REQUIRED_SINGLE_VENDOR = _env_float("JOYGATE_WITNESS_SCORE_REQUIRED_SINGLE_VENDOR", 1.9)
WITNESS_MIN_DISTINCT_VENDORS = max(_env_int("JOYGATE_WITNESS_MIN_DISTINCT_VENDORS", 2), 2)
WITNESS_MIN_DISTINCT_VENDORS_RISKY = max(_env_int("JOYGATE_WITNESS_MIN_DISTINCT_VENDORS_RISKY", 3), 2)
WITNESS_SCORE_REQUIRED_RISKY = _env_float("JOYGATE_WITNESS_SCORE_REQUIRED_RISKY", 2.5)
WITNESS_MIN_MARGIN_RISKY = max(_env_float("JOYGATE_WITNESS_MIN_MARGIN_RISKY", 1.0), 0.0)
WITNESS_CERTIFIED_POINTS_THRESHOLD = _env_int("JOYGATE_WITNESS_CERTIFIED_POINTS_THRESHOLD", 80)
WITNESS_MIN_CERTIFIED_SUPPORT_RISKY = max(_env_int("JOYGATE_WITNESS_MIN_CERTIFIED_SUPPORT_RISKY", 1), 1)

# Witness SLA 超时（分钟，内部 env，不进 FIELD_REGISTRY）
WITNESS_SLA_TIMEOUT_MINUTES = _env_float("JOYGATE_WITNESS_SLA_TIMEOUT_MINUTES", 3.0)


# M7.9：import 阶段不 raise；witness 配置错误时回退默认并写入 _STARTUP_WARNINGS，由 lifespan 统一打印。
_STARTUP_WARNINGS: list[str] = []


def _default_witness_triple() -> tuple[set[str], dict[str, str], dict[str, int]]:
    """返回内置默认 witness 三元组（保证不抛）。"""
    data = {
        "vendor_alpha": [{"joykey": "w1", "points": 60}, {"joykey": "alpha_02"}],
        "vendor_bravo": [{"joykey": "w2", "points": 60}],
        "vendor_charlie": [{"joykey": "charlie_01"}, {"joykey": "charlie_02", "points": 80}],
        "vendor_delta": [{"joykey": "delta_01"}],
        "vendor_echo": [{"joykey": "echo_01"}, {"joykey": "echo_02"}],
    }
    allowed_joykeys: set[str] = set()
    joykey_to_vendor: dict[str, str] = {}
    joykey_to_points: dict[str, int] = {}
    for vendor, robots in data.items():
        for robot in robots:
            joykey = (robot.get("joykey") or "").strip() or "unknown"
            points = robot.get("points", 60)
            if not isinstance(points, int):
                points = 60
            allowed_joykeys.add(joykey)
            joykey_to_vendor[joykey] = vendor
            joykey_to_points[joykey] = points
    return allowed_joykeys, joykey_to_vendor, joykey_to_points


def try_load_witness_robots_config() -> tuple[set[str], dict[str, str], dict[str, int], str | None]:
    """
    加载 witness 机器人白名单（内部 env，不进 FIELD_REGISTRY）。
    无论 env 是否配置错误，均不在本函数内 raise；非法时回退默认并返回 warning 人话。
    返回：(allowed_joykeys, joykey_to_vendor, joykey_to_points, warning_msg_or_none)
    """
    raw = os.getenv("JOYGATE_WITNESS_ROBOTS_JSON")
    if not raw or not raw.strip():
        return (*_default_witness_triple(), None)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _STARTUP_WARNINGS.append(
            f"JOYGATE_WITNESS_ROBOTS_JSON JSON 解析失败（{e!s}），已回退默认 witness 配置。"
        )
        return (*_default_witness_triple(), _STARTUP_WARNINGS[-1])

    if not isinstance(data, dict):
        _STARTUP_WARNINGS.append(
            "JOYGATE_WITNESS_ROBOTS_JSON 必须为 JSON 对象 {vendor: [robots...]}，已回退默认 witness 配置。"
        )
        return (*_default_witness_triple(), _STARTUP_WARNINGS[-1])

    vendors = list(data.keys())
    if len(vendors) != 5:
        _STARTUP_WARNINGS.append(
            f"witness 配置须恰好 5 个 vendor，当前 {len(vendors)} 个，已回退默认 witness 配置。"
        )
        return (*_default_witness_triple(), _STARTUP_WARNINGS[-1])

    allowed_joykeys = set()
    joykey_to_vendor: dict[str, str] = {}
    joykey_to_points: dict[str, int] = {}
    try:
        for vendor, robots in data.items():
            if not isinstance(robots, list) or not (1 <= len(robots) <= 5):
                raise ValueError(f"vendor {vendor!r} robots 须为 list 且长度 1~5")
            for robot in robots:
                if not isinstance(robot, dict):
                    raise ValueError(f"robot 须为 object")
                joykey_raw = robot.get("joykey")
                if not isinstance(joykey_raw, str) or not joykey_raw.strip():
                    raise ValueError(f"joykey 须为非空字符串")
                joykey = joykey_raw.strip()
                if joykey in allowed_joykeys:
                    raise ValueError(f"重复 joykey {joykey!r}")
                points = robot.get("points", 60)
                if not isinstance(points, int):
                    raise ValueError(f"points 须为 int")
                allowed_joykeys.add(joykey)
                joykey_to_vendor[joykey] = vendor
                joykey_to_points[joykey] = points
    except ValueError as e:
        _STARTUP_WARNINGS.append(f"witness 配置校验失败（{e!s}），已回退默认 witness 配置。")
        return (*_default_witness_triple(), _STARTUP_WARNINGS[-1])

    return allowed_joykeys, joykey_to_vendor, joykey_to_points, None


# Witness 机器人 allowlist（内部配置；只读结构，不进 FIELD_REGISTRY）
_load_result = try_load_witness_robots_config()
_allowed_joykeys_set = _load_result[0]
JOYKEY_TO_VENDOR = _load_result[1]
JOYKEY_TO_POINTS = _load_result[2]
# warning 已在 try_load 内写入 _STARTUP_WARNINGS（若有）
ALLOWED_WITNESS_JOYKEYS = frozenset(_allowed_joykeys_set)


# --- AI Jobs 留存（内部 env，不进 FIELD_REGISTRY）---
AI_JOB_RETENTION_SECONDS = _env_int("JOYGATE_AI_JOB_RETENTION_SECONDS", 3600)
# M12A-1：视觉审计每日调用预算（超限不调 Gemini，job 完成写 skipped due to budget）
JOYGATE_AI_DAILY_BUDGET_CALLS = _env_int("JOYGATE_AI_DAILY_BUDGET_CALLS", 10)
# M12A-1：Demo Day 长度（秒），跨日则 _ai_daily_calls_count 归零；默认 300
AI_BUDGET_DAY_SECONDS = _env_int("JOYGATE_AI_BUDGET_DAY_SECONDS", 300)
# M12A-1：mock | gemini（默认 mock）
JOYGATE_AI_PROVIDER = (os.getenv("JOYGATE_AI_PROVIDER") or "mock").strip().lower() or "mock"
JOYGATE_GEMINI_MODEL = os.getenv("JOYGATE_GEMINI_MODEL", "gemini-3.0-flash")


# --- Outbound Webhooks（内部 env，不进 FIELD_REGISTRY；对应 webhook_* policy config）---
_WEBHOOK_TIMEOUT_RAW = _env_int("JOYGATE_WEBHOOK_TIMEOUT_SECONDS", 10)
WEBHOOK_TIMEOUT_SECONDS = _WEBHOOK_TIMEOUT_RAW if _WEBHOOK_TIMEOUT_RAW > 0 else 10
_WEBHOOK_RETRY_RAW = _env_int("JOYGATE_WEBHOOK_RETRY_MAX_ATTEMPTS", 3)
WEBHOOK_RETRY_MAX_ATTEMPTS = _WEBHOOK_RETRY_RAW if _WEBHOOK_RETRY_RAW >= 0 else 3
_WEBHOOK_BACKOFF_RAW = _env_int("JOYGATE_WEBHOOK_RETRY_BACKOFF_SECONDS", 5)
WEBHOOK_RETRY_BACKOFF_SECONDS = _WEBHOOK_BACKOFF_RAW if _WEBHOOK_BACKOFF_RAW >= 0 else 5
# Webhook deliveries（内存态留存；不进 FIELD_REGISTRY）
WEBHOOK_DELIVERY_RETENTION_SECONDS = _env_int("WEBHOOK_DELIVERY_RETENTION_SECONDS", 3600)
# target_url 校验：仅 https 默认；http 与 localhost 需显式开启（本地 demo 用）
JOYGATE_WEBHOOK_ALLOW_HTTP = _env_bool("JOYGATE_WEBHOOK_ALLOW_HTTP", False)
JOYGATE_WEBHOOK_ALLOW_LOCALHOST = _env_bool("JOYGATE_WEBHOOK_ALLOW_LOCALHOST", False)
WEBHOOK_TARGET_URL_MAX_LEN = 2048


# --- M14.1 Policy Config（制度参数｜FIELD_REGISTRY §4；默认值只在此处写一次，env 可覆盖）---
# SOFT 复核/升级、路段 witness、新鲜度、视觉预算熔断
_soft_recheck = _env_int("JOYGATE_SOFT_HAZARD_RECHECK_INTERVAL_MINUTES", 5)
SOFT_HAZARD_RECHECK_INTERVAL_MINUTES = _soft_recheck if _soft_recheck > 0 else 5
_soft_escalate = _env_int("JOYGATE_SOFT_HAZARD_ESCALATE_AFTER_RECHECKS", 2)
SOFT_HAZARD_ESCALATE_AFTER_RECHECKS = _soft_escalate if _soft_escalate > 0 else 2
_seg_votes = _env_int("JOYGATE_SEGMENT_WITNESS_VOTES_REQUIRED", 2)
SEGMENT_WITNESS_VOTES_REQUIRED = _seg_votes if _seg_votes > 0 else 2
_seg_sla = _env_int("JOYGATE_SEGMENT_WITNESS_SLA_TIMEOUT_MINUTES", 1)
SEGMENT_WITNESS_SLA_TIMEOUT_MINUTES = _seg_sla if _seg_sla > 0 else 1
_seg_fresh = _env_int("JOYGATE_SEGMENT_FRESHNESS_WINDOW_MINUTES", 10)
SEGMENT_FRESHNESS_WINDOW_MINUTES = _seg_fresh if _seg_fresh > 0 else 10
_vision_global = _env_int("JOYGATE_VISION_AUDIT_BUDGET_GLOBAL", 50)
VISION_AUDIT_BUDGET_GLOBAL = _vision_global if _vision_global >= 0 else 50
_vision_vendor = _env_int("JOYGATE_VISION_AUDIT_BUDGET_PER_VENDOR", 10)
VISION_AUDIT_BUDGET_PER_VENDOR = _vision_vendor if _vision_vendor >= 0 else 10

# --- Demo 时间缩放（FIELD_REGISTRY §4 demo_minute_seconds）---
_DEMO_MIN_RAW = _env_int("JOYGATE_DEMO_MINUTE_SECONDS", 60)
DEMO_MINUTE_SECONDS = _DEMO_MIN_RAW if _DEMO_MIN_RAW > 0 else 60  # 1“分钟”对应的秒数；设为 5 时 demo 中 1 分钟=5 秒

# 只读 dict，供 store.get_policy() 及后续模块读取；不新增对外 API 字段。
# POLICY_CONFIG 现在覆盖 §4 中与 witness/hazard/vision-budget 相关 key，且 key 名与 FIELD_REGISTRY 一致。
POLICY_CONFIG = MappingProxyType({
    "soft_hazard_recheck_interval_minutes": SOFT_HAZARD_RECHECK_INTERVAL_MINUTES,
    "soft_hazard_escalate_after_rechecks": SOFT_HAZARD_ESCALATE_AFTER_RECHECKS,
    "segment_witness_votes_required": SEGMENT_WITNESS_VOTES_REQUIRED,
    "segment_witness_sla_timeout_minutes": SEGMENT_WITNESS_SLA_TIMEOUT_MINUTES,
    "segment_freshness_window_minutes": SEGMENT_FRESHNESS_WINDOW_MINUTES,
    "vision_audit_budget_global": VISION_AUDIT_BUDGET_GLOBAL,
    "vision_audit_budget_per_vendor": VISION_AUDIT_BUDGET_PER_VENDOR,
    "witness_votes_required": WITNESS_VOTES_REQUIRED,
    "witness_sla_timeout_minutes": int(round(WITNESS_SLA_TIMEOUT_MINUTES)),
    "demo_minute_seconds": DEMO_MINUTE_SECONDS,
})
# 自审：未新增 FIELD_REGISTRY 中未出现的对外字段/枚举；默认值仅在此块；后续模块只读此处，不 hardcode 数值。


def minute_to_seconds(minutes: int | float) -> int:
    """把配置的「分钟」换算为秒；使用 DEMO_MINUTE_SECONDS，demo 时可缩放（如 5 表示 1 分钟=5 秒）。minutes>0 且结果为 0 时返回 1 防 0 秒窗口。"""
    seconds = int(minutes * DEMO_MINUTE_SECONDS)
    if minutes > 0 and seconds < 1:
        return 1
    return seconds


# --- Dashboard “今日”统计模式（内部使用，不进 FIELD_REGISTRY）---
_raw_day_mode = os.getenv("JOYGATE_DASHBOARD_DAY_MODE", "DEMO")
_raw_day_mode_upper = (_raw_day_mode or "").upper()
DASHBOARD_DAY_MODE = _raw_day_mode_upper if _raw_day_mode_upper in {"DEMO", "CALENDAR"} else "DEMO"
_DEMO_RAW = _env_int("JOYGATE_DEMO_DAY_SECONDS", 300)
DEMO_DAY_SECONDS = _DEMO_RAW if _DEMO_RAW > 0 else 300  # 守护：避免 0/负值导致 demo 日长度异常
DASHBOARD_TZ_OFFSET_HOURS = _env_int("JOYGATE_DASHBOARD_TZ_OFFSET_HOURS", 0)
