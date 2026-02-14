#!/usr/bin/env python3
"""
验收：1) /v1/snapshot 必有 hazards 字段且为 list；2) /v1/hazards 的 hazard_status 仅 OPEN/SOFT_BLOCKED/HARD_BLOCKED；
3) 用 segment_respond(observation BLOCKED) 推进 cell 到 SOFT_BLOCKED，再 GET /v1/hazards 验证该 cell 为 SOFT_BLOCKED。
"""
from __future__ import annotations

import argparse
import sys

import requests

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
FORMAL_STATUSES = {"OPEN", "SOFT_BLOCKED", "HARD_BLOCKED"}
TEST_SEGMENT = "cell_1_1"


def main() -> int:
    parser = argparse.ArgumentParser(description="hazards not omitted + /v1/hazards formal status proof")
    parser.add_argument("--base_url", default=BASE_URL_DEFAULT)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # 1) GET bootstrap
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}", file=sys.stderr)
        return 1
    if not session.cookies.get("joygate_sandbox"):
        print("FAIL: no joygate_sandbox cookie", file=sys.stderr)
        return 1
    print("1) GET /bootstrap OK")

    # 2) GET /v1/snapshot：必有 hazards 且为 list
    r = session.get(f"{base}/v1/snapshot", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET /v1/snapshot {r.status_code}", file=sys.stderr)
        return 1
    try:
        data = r.json()
    except Exception:
        print("FAIL: snapshot not JSON", file=sys.stderr)
        return 1
    if "hazards" not in data:
        print("FAIL: /v1/snapshot 缺少 hazards 字段", file=sys.stderr)
        return 1
    hazards = data["hazards"]
    if not isinstance(hazards, list):
        print(f"FAIL: /v1/snapshot hazards 不是 list: {type(hazards)}", file=sys.stderr)
        return 1
    print(f"2) GET /v1/snapshot OK：hazards 存在且为 list，len={len(hazards)}")

    # 3) GET /v1/hazards：hazard_status 仅 OPEN | SOFT_BLOCKED | HARD_BLOCKED
    r = session.get(f"{base}/v1/hazards", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET /v1/hazards {r.status_code}", file=sys.stderr)
        return 1
    try:
        data = r.json()
    except Exception:
        print("FAIL: hazards not JSON", file=sys.stderr)
        return 1
    hazards_list = data.get("hazards") or []
    for item in hazards_list:
        st = item.get("hazard_status")
        if st not in FORMAL_STATUSES:
            print(f"FAIL: /v1/hazards 出现非正式值 hazard_status={st!r}，仅允许 OPEN/SOFT_BLOCKED/HARD_BLOCKED", file=sys.stderr)
            return 1
    print(f"3) GET /v1/hazards OK：全部 hazard_status 为正式值，共 {len(hazards_list)} 条")

    # 4) POST /v1/witness/segment_respond（observation BLOCKED）推进 cell 到 SOFT_BLOCKED
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={
            "segment_id": TEST_SEGMENT,
            "hazard_status": "BLOCKED",
            "points_event_id": "pe_haz_proof_1",
        },
        timeout=timeout,
    )
    if r.status_code != 204:
        print(f"FAIL: POST /v1/witness/segment_respond {r.status_code} {r.text[:200]}", file=sys.stderr)
        return 1
    print("4) POST /v1/witness/segment_respond hazard_status=BLOCKED OK -> 204")

    # 5) GET /v1/hazards：该 cell 的 hazard_status=SOFT_BLOCKED
    r = session.get(f"{base}/v1/hazards", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET /v1/hazards (second) {r.status_code}", file=sys.stderr)
        return 1
    data = r.json()
    hazards_list = data.get("hazards") or []
    found = None
    for item in hazards_list:
        if item.get("segment_id") == TEST_SEGMENT:
            found = item
            break
    if not found:
        print(f"FAIL: GET /v1/hazards 未找到 segment_id={TEST_SEGMENT}", file=sys.stderr)
        return 1
    if found.get("hazard_status") != "SOFT_BLOCKED":
        print(f"FAIL: segment {TEST_SEGMENT} hazard_status={found.get('hazard_status')!r}，期望 SOFT_BLOCKED", file=sys.stderr)
        return 1
    print(f"5) GET /v1/hazards OK：segment_id={TEST_SEGMENT} hazard_status=SOFT_BLOCKED")

    print("PASS: hazards 不省略 + /v1/hazards 正式值验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
