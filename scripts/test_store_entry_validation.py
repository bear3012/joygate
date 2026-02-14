#!/usr/bin/env python3
"""
按 docs_control_center/API_REVIEW_STORE_ENTRY_VALIDATION.md 清单，
对 store 入口收紧（禁止前后空白 + ≤64）做负例测试；期望 400（或 403）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def bootstrap(base_url: str, timeout: float):
    r = requests.get(base_url.rstrip("/") + "/bootstrap", timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"bootstrap {r.status_code}")
    return r.cookies


def main() -> int:
    p = argparse.ArgumentParser(description="Store entry validation negative tests")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout

    try:
        cookies = bootstrap(base, timeout)
    except Exception as e:
        print(f"SKIP: bootstrap failed: {e}")
        return 0

    session = requests.Session()
    session.cookies.update(cookies)
    ok = 0
    fail = 0

    # ----- 1) record_segment_passed_telemetry -----
    now = time.time()
    # joykey 前空白
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": " r1",
            "fleet_id": None,
            "segment_ids": ["cell_0_0"],
            "event_occurred_at": now,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400 and ("invalid joykey" in (r.json().get("detail") or "").lower() or "invalid" in str(r.json().get("detail", "")).lower()):
        ok += 1
        print("PASS: telemetry joykey leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry joykey leading space -> {r.status_code} {r.text[:200]}")

    # joykey 后空白
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r1 ",
            "fleet_id": None,
            "segment_ids": ["cell_0_0"],
            "event_occurred_at": now,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry joykey trailing space -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry joykey trailing space -> {r.status_code}")

    # joykey 65 字符
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r" + "x" * 64,
            "fleet_id": None,
            "segment_ids": ["cell_0_0"],
            "event_occurred_at": now,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry joykey len 65 -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry joykey len 65 -> {r.status_code}")

    # segment_ids 项前空白
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r1",
            "fleet_id": None,
            "segment_ids": [" cell_0_0"],
            "event_occurred_at": now,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry segment_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry segment_id leading space -> {r.status_code}")

    # ----- 2) record_segment_witness -----
    # segment_id 前空白
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={
            "segment_id": " cell_0_0",
            "segment_state": "BLOCKED",
            "points_event_id": "pe_01",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: witness segment_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: witness segment_id leading space -> {r.status_code}")

    # points_event_id 前空白
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "w1"},
        json={
            "segment_id": "cell_0_0",
            "segment_state": "BLOCKED",
            "points_event_id": " pe_02",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: witness points_event_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: witness points_event_id leading space -> {r.status_code}")

    # ----- 3) update_incident_status -----
    # incident_id 前空白（无需真实 incident，路由/store 先校验格式）
    r = session.post(
        f"{base}/v1/incidents/update_status",
        json={"incident_id": " inc_nonexist", "incident_status": "RESOLVED"},
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: update_status incident_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: update_status incident_id leading space -> {r.status_code}")

    # incident_id 后空白
    r = session.post(
        f"{base}/v1/incidents/update_status",
        json={"incident_id": "inc_nonexist ", "incident_status": "RESOLVED"},
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: update_status incident_id trailing space -> 400")
    else:
        fail += 1
        print(f"FAIL: update_status incident_id trailing space -> {r.status_code}")

    # ----- 4) create_dispatch_explain_job（可选）-----
    r = session.post(
        f"{base}/v1/ai/dispatch_explain",
        json={
            "hold_id": " hold_1",
            "audience": "ops",
            "dispatch_reason_codes": ["BLOCKED_BY_OTHER"],
            "context_ref": None,
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: dispatch_explain hold_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: dispatch_explain hold_id leading space -> {r.status_code}")

    # ----- 5) create_policy_suggest_job（可选）-----
    r = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": " inc_1", "context_ref": None},
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: policy_suggest incident_id leading space -> 400")
    else:
        fail += 1
        print(f"FAIL: policy_suggest incident_id leading space -> {r.status_code}")

    # ----- 6) 扩展：truth_input_source 非法枚举 / segment_ids>200 / event_occurred_at 过未来 / witness 非白名单 / audience 空白 / context_ref 空白 -----
    # truth_input_source 非法枚举 -> 400
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r1",
            "fleet_id": None,
            "segment_ids": ["cell_0_0"],
            "event_occurred_at": now,
            "truth_input_source": "INVALID_SOURCE",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry truth_input_source invalid enum -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry truth_input_source invalid enum -> {r.status_code}")

    # segment_ids 数量 > 200 -> 400
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r1",
            "fleet_id": None,
            "segment_ids": [f"cell_{i}_0" for i in range(201)],
            "event_occurred_at": now,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry segment_ids count > 200 -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry segment_ids count > 200 -> {r.status_code}")

    # event_occurred_at 过未来 (> ALLOWED_FUTURE_SKEW_SECONDS) -> 400
    future_ts = time.time() + 120
    r = session.post(
        f"{base}/v1/telemetry/segment_passed",
        json={
            "joykey": "r1",
            "fleet_id": None,
            "segment_ids": ["cell_0_0"],
            "event_occurred_at": future_ts,
            "truth_input_source": "SIMULATOR",
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: telemetry event_occurred_at too far future -> 400")
    else:
        fail += 1
        print(f"FAIL: telemetry event_occurred_at too far future -> {r.status_code}")

    # witness 非白名单 (X-JoyKey 不在 ALLOWED_WITNESS_JOYKEYS) -> 403
    r = session.post(
        f"{base}/v1/witness/segment_respond",
        headers={"X-JoyKey": "unknown_witness_key"},
        json={
            "segment_id": "cell_0_0",
            "segment_state": "BLOCKED",
            "points_event_id": "pe_99",
        },
        timeout=timeout,
    )
    if r.status_code == 403:
        ok += 1
        print("PASS: witness X-JoyKey not in whitelist -> 403")
    else:
        fail += 1
        print(f"FAIL: witness X-JoyKey not in whitelist -> {r.status_code}")

    # dispatch_explain audience 前后空白 -> 400
    r = session.post(
        f"{base}/v1/ai/dispatch_explain",
        json={
            "hold_id": "hold_1",
            "audience": " ops ",
            "dispatch_reason_codes": ["BLOCKED_BY_OTHER"],
            "context_ref": None,
        },
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: dispatch_explain audience leading/trailing space -> 400")
    else:
        fail += 1
        print(f"FAIL: dispatch_explain audience leading/trailing space -> {r.status_code}")

    # policy_suggest context_ref 前后空白 -> 400
    r = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None, "context_ref": " ref1 "},
        timeout=timeout,
    )
    if r.status_code == 400:
        ok += 1
        print("PASS: policy_suggest context_ref leading/trailing space -> 400")
    else:
        fail += 1
        print(f"FAIL: policy_suggest context_ref leading/trailing space -> {r.status_code}")

    print("")
    print(f"Result: {ok} passed, {fail} failed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
