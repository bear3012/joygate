#!/usr/bin/env python3
"""segment_passed 单次请求 segment_ids 数量上限：200 条 204，201 条 400 (too many segment_ids)。"""
from __future__ import annotations

import argparse
import sys
import time

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Telemetry segment_ids limit: 200 -> 204, 201 -> 400")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    session = requests.Session()

    # 第一步：POST bootstrap 拿到 sandbox cookie（项目脚本用 GET /bootstrap）
    r_boot = session.get(f"{base}/bootstrap", timeout=args.timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: bootstrap {r_boot.status_code}", file=sys.stderr)
        return 1
    if not session.cookies.get("joygate_sandbox"):
        print("FAIL: bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        return 1

    url = f"{base}/v1/telemetry/segment_passed"
    # truth_input_source 使用 telemetry_logic.ALLOWED_TRUTH_INPUT_SOURCES 中的值
    truth_input_source = "SIMULATOR"
    event_occurred_at = time.time()

    # 第二步：200 个合法 segment_id -> 204
    segment_ids_200 = [f"cell_0_{i}" for i in range(200)]
    payload_200 = {
        "joykey": "jk_limit_test",
        "segment_ids": segment_ids_200,
        "event_occurred_at": event_occurred_at,
        "truth_input_source": truth_input_source,
    }
    r200 = session.post(url, json=payload_200, timeout=args.timeout)
    if r200.status_code != 204:
        print(f"FAIL: 200 segment_ids -> {r200.status_code} body={r200.text}", file=sys.stderr)
        return 1
    print("OK: 200 segment_ids -> 204")

    # 第三步：201 个合法 segment_id -> 400，detail 包含 "too many segment_ids"
    segment_ids_201 = [f"cell_0_{i}" for i in range(201)]
    payload_201 = {
        "joykey": "jk_limit_test",
        "segment_ids": segment_ids_201,
        "event_occurred_at": event_occurred_at,
        "truth_input_source": truth_input_source,
    }
    r201 = session.post(url, json=payload_201, timeout=args.timeout)
    if r201.status_code != 400:
        print(f"FAIL: 201 segment_ids -> expected 400, got {r201.status_code} body={r201.text}", file=sys.stderr)
        return 1
    detail = r201.json().get("detail", "") if r201.headers.get("content-type", "").startswith("application/json") else r201.text
    if "too many segment_ids" not in str(detail):
        print(f"FAIL: 201 response detail must contain 'too many segment_ids', got: {detail}", file=sys.stderr)
        return 1
    print("OK: 201 segment_ids -> 400 (too many segment_ids)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
