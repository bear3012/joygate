from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from threading import Lock
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from joygate.config import (
    _env_int,
    ALLOW_SANDBOX_HEADER,
    MAX_SANDBOXES,
    RATE_LIMIT_PER_IP_PER_MIN,
    RATE_LIMIT_PER_SANDBOX_PER_MIN,
    REQUIRE_SINGLE_WORKER,
    SANDBOX_IDLE_TTL_SECONDS,
)
from joygate.store import JoyGateStore

SANDBOX_ID_RE = re.compile(r"^[a-f0-9]{1,32}$")
SIG_RE = re.compile(r"^sha256=[0-9a-f]{64}$")

# 内部配置（不进 FIELD_REGISTRY）
SANDBOX_HEADER_SECRET = (os.getenv("JOYGATE_SANDBOX_HEADER_SECRET") or "").strip()
SANDBOX_HEADER_TTL_SECONDS = _env_int("JOYGATE_SANDBOX_HEADER_TTL_SECONDS", 300)

# 沙盒管理
_SANDBOX_STORES: dict[str, JoyGateStore] = {}
_SANDBOX_LAST_SEEN: dict[str, float] = {}
_SANDBOX_LOCK = Lock()

# 限流计数
_RL_SANDBOX: dict[tuple[str, int], int] = {}
_RL_IP: dict[tuple[str, int], int] = {}
_RL_LOCK = Lock()


# 单 worker 护栏（在 import 期检查）
if REQUIRE_SINGLE_WORKER:
    web_concurrency = _env_int("WEB_CONCURRENCY", 0)
    uvicorn_workers = _env_int("UVICORN_WORKERS", 0)
    if web_concurrency > 1 or uvicorn_workers > 1:
        raise RuntimeError(
            "本 demo 沙盒为进程内内存态，请用 --workers 1 启动 uvicorn。"
            f"检测到 WEB_CONCURRENCY={web_concurrency} 或 UVICORN_WORKERS={uvicorn_workers}。"
            "如需关闭此检查，设置 JOYGATE_REQUIRE_SINGLE_WORKER=0"
        )

if ALLOW_SANDBOX_HEADER and not SANDBOX_HEADER_SECRET:
    raise RuntimeError("JOYGATE_ALLOW_SANDBOX_HEADER=1 requires JOYGATE_SANDBOX_HEADER_SECRET")


def _expected_sandbox_sig(secret: str, ts: int, sandbox_id: str) -> str:
    msg = f"{ts}.{sandbox_id}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _verify_sandbox_header(sandbox_id: str, ts_raw: str | None, sig_raw: str | None) -> bool:
    if not SANDBOX_ID_RE.fullmatch(sandbox_id):
        return False
    sig = (sig_raw or "").strip().lower()
    if not SIG_RE.fullmatch(sig):
        return False
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if ts < now - SANDBOX_HEADER_TTL_SECONDS:
        return False
    if ts > now + SANDBOX_HEADER_TTL_SECONDS:
        return False
    expected = _expected_sandbox_sig(SANDBOX_HEADER_SECRET, ts, sandbox_id).lower()
    return hmac.compare_digest(expected, sig)


def _new_sandbox_id() -> str:
    """生成新的沙盒 ID（短 token）"""
    return uuid.uuid4().hex[:16]


def _get_sandbox_id(request: Request) -> Tuple[Optional[str], bool]:
    """
    从 cookie 或 header 获取 sandbox_id，返回 (sandbox_id, from_cookie)
    - 先读 cookie joygate_sandbox，有则直接 return (cookie, True)（忽略 header）
    - 无 cookie 且 ALLOW_SANDBOX_HEADER 时读 header，校验失败则 raise ValueError
    """
    sandbox_id = request.cookies.get("joygate_sandbox")
    if sandbox_id:
        return sandbox_id, True
    if ALLOW_SANDBOX_HEADER:
        sandbox_id = (request.headers.get("X-JoyGate-Sandbox") or "").strip()
        if sandbox_id:
            ts = request.headers.get("X-JoyGate-Sandbox-Timestamp")
            sig = request.headers.get("X-JoyGate-Sandbox-Signature")
            if not _verify_sandbox_header(sandbox_id, ts, sig):
                raise ValueError("invalid sandbox header")
            return sandbox_id, False
    return None, False


def _get_or_create_store(sandbox_id: Optional[str], from_cookie: bool) -> Tuple[JoyGateStore, str, bool]:
    """
    获取或创建 store，返回 (store, sandbox_id, need_set_cookie)
    在锁内进行沙盒回收和创建
    
    Args:
        sandbox_id: 从 header 或 cookie 获取的 sandbox_id（可能为 None）
        from_cookie: 是否来自 cookie
    """
    need_set_cookie = False
    
    with _SANDBOX_LOCK:
        now_ts = time.time()
        
        # 回收超过 TTL 的沙盒
        to_delete = []
        for sid, last_seen in _SANDBOX_LAST_SEEN.items():
            if (now_ts - last_seen) > SANDBOX_IDLE_TTL_SECONDS:
                to_delete.append(sid)
        for sid in to_delete:
            _SANDBOX_STORES.pop(sid, None)
            _SANDBOX_LAST_SEEN.pop(sid, None)
        # 若仍超过 MAX_SANDBOXES：按 LRU（最近访问时间）淘汰最老的直到满足上限
        while len(_SANDBOX_STORES) > MAX_SANDBOXES:
            oldest_sid = min(_SANDBOX_LAST_SEEN.keys(), key=lambda s: _SANDBOX_LAST_SEEN[s])
            _SANDBOX_STORES.pop(oldest_sid, None)
            _SANDBOX_LAST_SEEN.pop(oldest_sid, None)
        logger.info("sandbox count=%s max=%s", len(_SANDBOX_STORES), MAX_SANDBOXES)
        
        # 无效 cookie 防护：cookie 里来的未知 sandbox_id 不能被信任
        if sandbox_id and from_cookie and sandbox_id not in _SANDBOX_STORES:
            sandbox_id = None
            from_cookie = False
        
        # 容量满且无法再淘汰时拒绝创建新沙盒（理论上 LRU 后 len<=MAX，此处为兜底）
        if len(_SANDBOX_STORES) >= MAX_SANDBOXES:
            if not (sandbox_id and sandbox_id in _SANDBOX_STORES):
                raise RuntimeError("sandbox capacity reached")
        
        # 创建新沙盒或获取现有
        if not sandbox_id:
            # 只有当 sandbox_id 为空时才生成新 id
            sandbox_id = _new_sandbox_id()
            _SANDBOX_STORES[sandbox_id] = JoyGateStore()
            need_set_cookie = True
        elif sandbox_id not in _SANDBOX_STORES:
            # sandbox_id 存在但不在 _SANDBOX_STORES 中（仅可能来自 header 且允许 header 时）：用该 id 建 store
            _SANDBOX_STORES[sandbox_id] = JoyGateStore()
            if not from_cookie:
                need_set_cookie = True
        
        # 更新 last_seen
        _SANDBOX_LAST_SEEN[sandbox_id] = now_ts
        store = _SANDBOX_STORES[sandbox_id]
    
    return store, sandbox_id, need_set_cookie


def _check_rate_limit(request: Request, sandbox_id: Optional[str]) -> Optional[Response]:
    """
    检查限流，返回 None 表示通过，返回 Response 表示被限流
    """
    now_ts = time.time()
    minute_bucket = int(now_ts // 60)
    client_ip = request.client.host if request.client else "unknown"

    with _RL_LOCK:
        # IP 级别限流
        ip_key = (client_ip, minute_bucket)
        ip_count = _RL_IP.get(ip_key, 0)
        if ip_count >= RATE_LIMIT_PER_IP_PER_MIN:
            return Response(status_code=429, content="rate limited", media_type="text/plain")
        _RL_IP[ip_key] = ip_count + 1

        # Sandbox 级别限流（如果有 sandbox_id）
        if sandbox_id:
            sandbox_key = (sandbox_id, minute_bucket)
            sandbox_count = _RL_SANDBOX.get(sandbox_key, 0)
            if sandbox_count >= RATE_LIMIT_PER_SANDBOX_PER_MIN:
                return Response(status_code=429, content="rate limited", media_type="text/plain")
            _RL_SANDBOX[sandbox_key] = sandbox_count + 1

        # 清理旧 bucket（删除所有 bucket < minute_bucket-1 的 key）
        cutoff_bucket = minute_bucket - 1
        keys_to_delete_ip = [k for k in _RL_IP.keys() if k[1] < cutoff_bucket]
        for k in keys_to_delete_ip:
            _RL_IP.pop(k, None)
        keys_to_delete_sandbox = [k for k in _RL_SANDBOX.keys() if k[1] < cutoff_bucket]
        for k in keys_to_delete_sandbox:
            _RL_SANDBOX.pop(k, None)

    return None


async def sandbox_middleware(request: Request, call_next):
    """自动沙盒分配 + 限流 + cookie 设置"""
    try:
        sandbox_id, from_cookie = _get_sandbox_id(request)
    except ValueError:
        return Response(status_code=400, content="invalid sandbox header", media_type="text/plain")
    
    # 先做 IP 限流（sandbox 限流只有在有 sandbox_id 时做）
    rate_limit_response = _check_rate_limit(request, sandbox_id)
    if rate_limit_response:
        return rate_limit_response

    # 免沙盒路径：不设置 store、不 set_cookie，直接透传（/bootstrap 不在豁免列表）
    _NO_SANDBOX_PATHS = ("/openapi.json", "/docs", "/redoc", "/favicon.ico")
    if request.url.path in _NO_SANDBOX_PATHS:
        return await call_next(request)

    # 对 POST 且路径以 "/v1/" 开头的请求：若 sandbox_id 为空，直接返回 400
    if request.method == "POST" and request.url.path.startswith("/v1/"):
        if not sandbox_id:
            return Response(status_code=400, content="missing sandbox", media_type="text/plain")
    
    # 获取或创建 store
    try:
        store, sandbox_id, need_set_cookie = _get_or_create_store(sandbox_id, from_cookie)
    except RuntimeError:
        if request.method == "GET" and request.url.path == "/bootstrap":
            return JSONResponse(
                status_code=200,
                content={"sandbox_id": None, "note": "sandbox capacity reached; try later"},
            )
        return Response(status_code=503, content="sandbox capacity reached", media_type="text/plain")
    
    # 将 store 放入 request.state
    request.state.store = store
    request.state.sandbox_id = sandbox_id
    
    # 调用下一个 handler
    response = await call_next(request)
    
    # 如果需要设置 cookie（FastAPI/Starlette Response 对象支持 set_cookie）
    if need_set_cookie:
        # Starlette Response 及其子类都支持 set_cookie
        response.set_cookie("joygate_sandbox", sandbox_id, httponly=True, max_age=86400 * 7, path="/", samesite="lax")  # 7 天
    
    return response
