# src/joygate/main.py
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from joygate.sandbox import sandbox_middleware
from joygate.routes.incidents import router as incidents_router
from joygate.routes.charging import router as charging_router
from joygate.routes.witness import router as witness_router
from joygate.routes.ai_jobs import router as ai_jobs_router
from joygate.routes.dashboard import router as dashboard_router
from joygate.routes.bootstrap import router as bootstrap_router
from joygate.routes.webhooks import router as webhooks_router
from joygate.routes.hazards import router as hazards_router
from joygate.routes.telemetry import router as telemetry_router
from joygate.routes.audit import router as audit_router
from joygate.routes.admin import router as admin_router
from joygate.routes.work_orders import router as work_orders_router
from joygate.routes.reputation import router as reputation_router
from joygate.routes.ui import router as ui_router
from joygate.config import POLICY_CONFIG

# M7.7a：进程持有 OS 文件锁（非阻塞独占），无 mtime/无 unlink/无 stale_seconds；进程退出锁自动释放。
_SINGLE_WORKER_LOCK_FILENAME = "joygate_single_worker.lock"
_SINGLE_WORKER_LOCK_FD: Optional[int] = None

_SINGLE_WORKER_ERROR_MSG = (
    "JoyGate requires --workers 1. Do not use --workers >1. Multiple workers use separate process memory, "
    "so sandbox/store state would be inconsistent. (--reload may spawn an extra process; avoid for production.) "
    "Start with: python -m uvicorn joygate.main:app --host 127.0.0.1 --port 8000 --workers 1"
)


def _acquire_single_worker_lock() -> None:
    global _SINGLE_WORKER_LOCK_FD
    if os.environ.get("JOYGATE_DISABLE_SINGLE_WORKER_LOCK") == "1":
        return
    if _SINGLE_WORKER_LOCK_FD is not None:
        return
    lock_dir = tempfile.gettempdir()
    lock_path = os.path.join(lock_dir, _SINGLE_WORKER_LOCK_FILENAME)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError(_SINGLE_WORKER_ERROR_MSG) from None
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                raise RuntimeError(_SINGLE_WORKER_ERROR_MSG) from None
        _SINGLE_WORKER_LOCK_FD = fd
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _run_startup_warnings() -> None:
    """M7.9：收集 witness 配置 / Pillow / Gemini 可选依赖告警，统一以 WARN: 打印到 stderr（仅启动时一次）。"""
    import sys
    warnings: list[str] = []
    try:
        from joygate import config
        warnings.extend(getattr(config, "_STARTUP_WARNINGS", []) or [])
    except Exception:
        pass
    try:
        from joygate import sim_render
        if getattr(sim_render, "Image", None) is None:
            warnings.append("缺 Pillow，vision_audit 渲染会失败。可安装: pip install Pillow")
    except Exception:
        warnings.append("缺 Pillow，vision_audit 渲染会失败。可安装: pip install Pillow")
    provider = (os.getenv("JOYGATE_AI_PROVIDER") or "").strip().lower()
    if provider == "gemini":
        joy_brain_ok = bool((os.getenv("JOY_BRAIN_BASE_URL") or "").strip()) and bool((os.getenv("JOY_BRAIN_KEY") or "").strip())
        if not joy_brain_ok:
            sdk_ok = False
            key_ok = bool((os.getenv("GEMINI_API_KEY") or "").strip())
            try:
                import google.genai  # noqa: F401
                sdk_ok = True
            except ImportError:
                pass
            if not sdk_ok:
                warnings.append("JOYGATE_AI_PROVIDER=gemini 但未安装 google-genai SDK，视觉审计将失败。可安装: pip install google-genai")
            if not key_ok:
                warnings.append("JOYGATE_AI_PROVIDER=gemini 但未设置 GEMINI_API_KEY（或 JOY_BRAIN_BASE_URL/JOY_BRAIN_KEY），视觉审计将失败。")
    for msg in warnings:
        print("WARN:", msg, file=sys.stderr)


def _release_single_worker_lock() -> None:
    global _SINGLE_WORKER_LOCK_FD
    if _SINGLE_WORKER_LOCK_FD is None:
        return
    fd = _SINGLE_WORKER_LOCK_FD
    _SINGLE_WORKER_LOCK_FD = None
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        _acquire_single_worker_lock()
        _run_startup_warnings()
        yield
    finally:
        _release_single_worker_lock()


app = FastAPI(title="JoyGate v0.3 - Hackathon Charger", lifespan=_lifespan)
app.middleware("http")(sandbox_middleware)
app.include_router(incidents_router)
app.include_router(charging_router)
app.include_router(witness_router)
app.include_router(ai_jobs_router)
app.include_router(dashboard_router)
app.include_router(bootstrap_router)
app.include_router(webhooks_router)
app.include_router(hazards_router)
app.include_router(telemetry_router)
app.include_router(audit_router)
app.include_router(admin_router)
app.include_router(work_orders_router)
app.include_router(reputation_router)
app.include_router(ui_router)