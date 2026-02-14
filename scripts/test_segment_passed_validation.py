"""
M10 /v1/telemetry/segment_passed 负例校验测试：断言无效请求返回 400。
覆盖：segment_ids 空、invalid truth_input_source、event_occurred_at 超未来、event_occurred_at 非法字符串。
"""
from __future__ import annotations

import argparse
import sys
import time

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="M10 segment_passed validation (negative cases)")
    parser.add_argument("--base_url", default="http://127.0.0.1:8010", help="Base URL of JoyGate API")
    parser.add_argument("--timeout_sec", type=float, default=5.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec
    session = requests.Session()

    # 必须先 GET /bootstrap 获取 joygate_sandbox cookie
    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"bootstrap failed: {r_boot.status_code}", file=sys.stderr)
        sys.exit(1)
    if not session.cookies.get("joygate_sandbox"):
        print("bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        sys.exit(1)
    print("bootstrap OK, cookie set")

    url = f"{base}/v1/telemetry/segment_passed"

    # (a) segment_ids = [] -> 400
    r = session.post(
        url,
        json={
            "joykey": "jk",
            "fleet_id": None,
            "segment_ids": [],
            "event_occurred_at": time.time(),
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    print(f"(a) segment_ids=[] -> status={r.status_code} body={r.text}")
    if r.status_code != 400:
        print(f"expected 400, got {r.status_code}", file=sys.stderr)
        sys.exit(1)

    # (b) truth_input_source = "BAD_SOURCE" -> 400
    r = session.post(
        url,
        json={
            "joykey": "jk",
            "fleet_id": None,
            "segment_ids": ["cell_1_1"],
            "event_occurred_at": time.time(),
            "truth_input_source": "BAD_SOURCE",
        },
        timeout=timeout,
    )
    print(f"(b) truth_input_source=BAD_SOURCE -> status={r.status_code} body={r.text}")
    if r.status_code != 400:
        print(f"expected 400, got {r.status_code}", file=sys.stderr)
        sys.exit(1)

    # (c) event_occurred_at = time.time()+9999 (future skew) -> 400
    r = session.post(
        url,
        json={
            "joykey": "jk",
            "fleet_id": None,
            "segment_ids": ["cell_1_1"],
            "event_occurred_at": time.time() + 9999,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    print(f"(c) event_occurred_at=now+9999 -> status={r.status_code} body={r.text}")
    if r.status_code != 400:
        print(f"expected 400, got {r.status_code}", file=sys.stderr)
        sys.exit(1)

    # (d) event_occurred_at = "not-a-time" -> 400
    r = session.post(
        url,
        json={
            "joykey": "jk",
            "fleet_id": None,
            "segment_ids": ["cell_1_1"],
            "event_occurred_at": "not-a-time",
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    print(f"(d) event_occurred_at=not-a-time -> status={r.status_code} body={r.text}")
    if r.status_code != 400:
        print(f"expected 400, got {r.status_code}", file=sys.stderr)
        sys.exit(1)

    # (e) segment_ids 格式非法：cell_a_b 不符合 cell_{x}_{y}
    r = session.post(
        url,
        json={
            "joykey": "jk",
            "fleet_id": None,
            "segment_ids": ["cell_a_b"],
            "event_occurred_at": time.time(),
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    print(f"(e) segment_ids=cell_a_b -> status={r.status_code} body={r.text}")
    if r.status_code != 400:
        print(f"expected 400, got {r.status_code}", file=sys.stderr)
        sys.exit(1)

    print("OK segment_passed validation (negative cases) passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
