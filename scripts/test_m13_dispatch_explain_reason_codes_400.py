#!/usr/bin/env python3
"""
M13.0 T1：dispatch_reason_codes 校验。
传入非法 reason code（如 HACK_ME）创建 explain job，期待 HTTP 400。
不启动服务：需先启动 uvicorn，再运行本脚本。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13 T1: invalid dispatch_reason_code -> 400")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK")

    body = {
        "hold_id": "hold_demo_t1",
        "audience": "USER",
        "dispatch_reason_codes": ["HACK_ME"],
    }
    r = session.post(f"{base}/v1/ai/dispatch_explain", json=body, timeout=timeout)
    if r.status_code != 400:
        print(f"FAIL: expected 400 for invalid dispatch_reason_code, got {r.status_code} {r.text}", file=sys.stderr)
        return 1
    print("PASS: invalid dispatch_reason_code (HACK_ME) -> 400")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
