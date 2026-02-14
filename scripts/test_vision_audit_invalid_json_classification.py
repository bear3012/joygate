#!/usr/bin/env python3
"""离线单测：Gemini 分支 JSONDecodeError 分流 -> summary=invalid JSON from provider；合法 JSON 正常解析。"""
from __future__ import annotations

import sys
import types

# 在导入 vision_audit_report_logic 之前注入 stub，否则 generate_vision_audit_result 内部的 import 会拿到真实模块
stub_return: list[str | None] = [None]

def _stub_gemini_vision_audit(_image_png_bytes: bytes, _prompt: str) -> str:
    out = stub_return[0]
    return out if out is not None else ""

stub_module = types.ModuleType("joygate.ai_provider_gemini")
stub_module.gemini_vision_audit = _stub_gemini_vision_audit
sys.modules["joygate.ai_provider_gemini"] = stub_module

from joygate.vision_audit_report_logic import generate_vision_audit_result  # noqa: E402


def main() -> int:
    incident_rec = {"incident_id": "inc_1", "incident_type": "BLOCKED"}
    image_bytes = b"1"

    # 非法 JSON（以 { 开头，触发 json.loads 报 JSONDecodeError）
    stub_return[0] = "{not json"
    result_invalid = generate_vision_audit_result("gemini", incident_rec=incident_rec, image_png_bytes=image_bytes)
    if result_invalid.get("summary") != "invalid JSON from provider":
        print(f"FAIL: invalid JSON -> summary={result_invalid.get('summary')!r}", file=sys.stderr)
        return 1
    if result_invalid.get("confidence") is not None:
        print(f"FAIL: invalid JSON -> confidence should be None, got {result_invalid.get('confidence')}", file=sys.stderr)
        return 1
    print("OK: invalid JSON -> summary=invalid JSON from provider, confidence=None")

    # 合法 JSON
    stub_return[0] = '{"summary":"ok","confidence":88}'
    result_valid = generate_vision_audit_result("gemini", incident_rec=incident_rec, image_png_bytes=image_bytes)
    if result_valid.get("summary") != "ok":
        print(f"FAIL: valid JSON -> summary={result_valid.get('summary')!r}", file=sys.stderr)
        return 1
    if result_valid.get("confidence") != 88:
        print(f"FAIL: valid JSON -> confidence should be 88, got {result_valid.get('confidence')}", file=sys.stderr)
        return 1
    print("OK: valid JSON -> summary=ok, confidence=88")
    return 0


if __name__ == "__main__":
    sys.exit(main())
