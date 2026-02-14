#!/usr/bin/env python3
"""
M13.2 B1：词典 vs 代码 reason codes 一致性检查（无需启动服务）。
解析 FIELD_REGISTRY dispatch_reason_code 列表，与 joygate.ai_jobs.DISPATCH_REASON_CODES 对比。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    reg_path = repo_root / "docs_control_center" / "FIELD_REGISTRY.md"
    text = reg_path.read_text(encoding="utf-8", errors="strict")

    # 定位 dispatch_reason_code: 小节，收集 - XXX 直到空行或下一 xxx:
    registry_codes: set[str] = set()
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^dispatch_reason_code\s*:", line):
            in_section = True
            continue
        if not in_section:
            continue
        if not stripped:
            break
        if stripped.startswith("- "):
            code = stripped[2:].strip()
            if code:
                registry_codes.add(code)
        elif not stripped.startswith("#"):
            break

    # 代码侧
    sys.path.insert(0, str(repo_root / "src"))
    from joygate.ai_jobs import DISPATCH_REASON_CODES

    code_set = set(DISPATCH_REASON_CODES)
    missing_in_code = registry_codes - code_set
    extra_in_code = code_set - registry_codes
    if missing_in_code or extra_in_code:
        print("FAIL: dispatch_reason_code registry vs code mismatch")
        if missing_in_code:
            print("  missing_in_code:", sorted(missing_in_code))
        if extra_in_code:
            print("  extra_in_code:", sorted(extra_in_code))
        return 1
    print(f"PASS: dispatch_reason_code registry sync (count={len(registry_codes)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
