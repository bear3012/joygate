"""
路由层统一入口校验：str + strip + 禁止前后空白 + 非空（required）+ 长度上限。
所有失败 HTTP 400，detail 形如 "invalid <field_name>"（snake_case）。
不新增 FIELD_REGISTRY 字段；仅防污染 cap，上限与 store 一致（ID 类 64）。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

ENTRY_MAX_ID_LEN = 64
EVIDENCE_REFS_MAX_COUNT = 5
EVIDENCE_REF_MAX_LEN = 120


def norm_required_str(field: str, v: Any, max_len: int = ENTRY_MAX_ID_LEN) -> str:
    """必填：str、raw==strip、strip 后非空、len≤max_len；否则 400 invalid <field>。"""
    if not isinstance(v, str):
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    s = v.strip()
    if v != s or not s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    return s


def norm_optional_str(field: str, v: Any, max_len: int = ENTRY_MAX_ID_LEN) -> str | None:
    """可选：None 或 str；str 时 raw==strip，strip 后空→None，len≤max_len；否则 400 invalid <field>。"""
    if v is None:
        return None
    if not isinstance(v, str):
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    s = v.strip()
    if not s:
        return None
    if v != s or len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    return s


def norm_evidence_refs(v: Any) -> list[str] | None:
    """evidence_refs：None→None；list，最多 5 条，每条 str、strip 非空、禁止前后空白、len≤120；否则 400 invalid evidence_refs。"""
    if v is None:
        return None
    if not isinstance(v, list):
        raise HTTPException(status_code=400, detail="invalid evidence_refs")
    if len(v) > EVIDENCE_REFS_MAX_COUNT:
        raise HTTPException(status_code=400, detail="invalid evidence_refs")
    out: list[str] = []
    for ref in v:
        if not isinstance(ref, str):
            raise HTTPException(status_code=400, detail="invalid evidence_refs")
        s = ref.strip()
        if ref != s or not s or len(s) > EVIDENCE_REF_MAX_LEN:
            raise HTTPException(status_code=400, detail="invalid evidence_refs")
        out.append(s)
    return out
