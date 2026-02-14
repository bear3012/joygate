#!/usr/bin/env python3
"""离线：AI 日预算按 Demo Day（JOYGATE_AI_BUDGET_DAY_SECONDS）重置，跨日 _ai_daily_calls_count 归零。"""
from __future__ import annotations

import os
import sys
import time

# 必须在 import joygate 前设置，否则 config 已加载
os.environ["JOYGATE_AI_BUDGET_DAY_SECONDS"] = "2"

from joygate.store import JoyGateStore  # noqa: E402
from joygate.config import AI_BUDGET_DAY_SECONDS  # noqa: E402


def main() -> int:
    store = JoyGateStore()

    # Case 1：同一天不 reset
    store._boot_ts = time.time()
    store._ai_daily_calls_date = "demo_0"
    store._ai_daily_calls_count = 7
    store.tick_ai_jobs(0)
    if store._ai_daily_calls_count != 7:
        print(f"FAIL: Case 1 expected count=7, got {store._ai_daily_calls_count}", file=sys.stderr)
        return 1
    print("OK: same demo day -> count unchanged (7)")

    # Case 2：跨天 reset
    store._boot_ts = time.time() - (AI_BUDGET_DAY_SECONDS + 1)
    store.tick_ai_jobs(0)
    if store._ai_daily_calls_count != 0:
        print(f"FAIL: Case 2 expected count=0, got {store._ai_daily_calls_count}", file=sys.stderr)
        return 1
    if store._ai_daily_calls_date == "demo_0":
        print(f"FAIL: Case 2 expected _ai_daily_calls_date != 'demo_0', got {store._ai_daily_calls_date!r}", file=sys.stderr)
        return 1
    print("OK: cross demo day -> count=0, date updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
