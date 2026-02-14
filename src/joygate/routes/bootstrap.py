from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/bootstrap")
def bootstrap(request: Request):
    """
    初始化沙盒并返回 sandbox_id（首次访问会设置 cookie）
    用于脚本/客户端首次访问时获取 sandbox cookie
    """
    sandbox_id = request.state.sandbox_id
    return {
        "sandbox_id": sandbox_id,
        "note": "Use cookie joygate_sandbox; run uvicorn with --workers 1",
    }
