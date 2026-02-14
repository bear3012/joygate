#!/usr/bin/env python3
"""订阅上限误伤回归：已有 50 个 enabled 时，创建 is_enabled=false 应 200，再创建 enabled 应 400。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_path = Path(__file__).resolve().parent
sys.path.insert(0, str(_path))
from _sandbox_client import get_bootstrapped_session  # noqa: E402

MAX = 50  # 与 store.MAX_WEBHOOK_SUBSCRIPTIONS 一致
# 使用公网 URL 避免依赖 JOYGATE_WEBHOOK_ALLOW_LOCALHOST
TARGET_URL = "https://example.com/webhook_cap_test"


def main() -> int:
    p = argparse.ArgumentParser(description="Webhook subscription cap regression: 50 enabled then disabled=200, enabled=400")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    session = get_bootstrapped_session(base, args.timeout)
    url = f"{base}/v1/webhooks/subscriptions"
    payload_enabled = {
        "target_url": TARGET_URL,
        "event_types": ["INCIDENT_CREATED"],
        "secret": None,
        "is_enabled": True,
    }
    payload_disabled = {
        "target_url": TARGET_URL,
        "event_types": ["INCIDENT_CREATED"],
        "secret": None,
        "is_enabled": False,
    }

    # 创建 50 个 enabled
    for i in range(MAX):
        r = session.post(url, json=payload_enabled, timeout=args.timeout)
        if r.status_code != 200:
            print(f"FAIL: create enabled #{i+1} -> {r.status_code} {r.text}", file=sys.stderr)
            return 1
        print(f"OK: created enabled #{i+1} -> 200")
    print("")

    # 创建 is_enabled=false 应 200
    r_disabled = session.post(url, json=payload_disabled, timeout=args.timeout)
    print(f"POST is_enabled=false -> {r_disabled.status_code} body={r_disabled.text[:200]}")
    if r_disabled.status_code != 200:
        print("FAIL: expected 200 for is_enabled=false", file=sys.stderr)
        return 1
    print("OK: is_enabled=false returned 200 (no cap hit)")
    print("")

    # 再创建 enabled 应 400
    r_enabled = session.post(url, json=payload_enabled, timeout=args.timeout)
    print(f"POST is_enabled=true (51st enabled) -> {r_enabled.status_code} body={r_enabled.text[:200]}")
    if r_enabled.status_code != 400:
        print("FAIL: expected 400 for 51st enabled", file=sys.stderr)
        return 1
    print("OK: is_enabled=true returned 400 (too many webhook subscriptions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
