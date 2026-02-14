#!/usr/bin/env python3
"""
M13.0 T2：解释摘要写入 ledger + 不泄露 context_ref/evidence_refs 原文。
构造 hold（reserve）-> 创建 dispatch_explain job（带 context_ref 原文）-> tick -> GET ledger。
断言：decisions 新增一条 decision_type=REROUTE_SUGGESTED；summary 含 dispatch_reason_codes，
且 不包含 原始 context_ref 字符串（只含 context_ref_hash）。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13 T2: dispatch_explain -> tick -> ledger decision + no context_ref leak")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # 1) bootstrap
    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK")

    # 2) reserve -> hold_id
    r_res = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": "charger-001", "joykey": "joy_m13_t2", "action": "HOLD"},
        timeout=timeout,
    )
    if r_res.status_code != 200:
        print(f"FAIL: POST /v1/reserve -> {r_res.status_code} {r_res.text}", file=sys.stderr)
        return 1
    hold_id = r_res.json().get("hold_id")
    if not hold_id:
        print("FAIL: reserve missing hold_id", file=sys.stderr)
        return 1
    print(f"reserve OK hold_id={hold_id}")

    # 3) 可选：report_blocked 以便 ledger 有 incident 可关联（非必须）
    r_rep = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "charger-001", "incident_type": "BLOCKED"},
        timeout=timeout,
    )
    if r_rep.status_code != 200:
        print(f"FAIL: report_blocked -> {r_rep.status_code}", file=sys.stderr)
        return 1
    print("report_blocked OK")

    # 4) GET ledger 初始 decisions 条数
    r_ledger0 = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger0.status_code != 200:
        print(f"FAIL: GET ledger -> {r_ledger0.status_code}", file=sys.stderr)
        return 1
    decisions_before = len(r_ledger0.json().get("decisions") or [])

    # 5) POST dispatch_explain（context_ref 为敏感原文，不应出现在 summary）
    secret_ref = "secret-context-must-not-appear-in-summary-12345"
    body = {
        "hold_id": hold_id,
        "obstacle_type": "BLOCKED_BY_CHARGER",
        "audience": "USER",
        "dispatch_reason_codes": ["CHARGER_BUSY", "INCIDENT_REPORTED"],
        "context_ref": secret_ref,
    }
    r_explain = session.post(f"{base}/v1/ai/dispatch_explain", json=body, timeout=timeout)
    if r_explain.status_code != 202:
        print(f"FAIL: POST dispatch_explain -> {r_explain.status_code} {r_explain.text}", file=sys.stderr)
        return 1
    ai_report_id = r_explain.json().get("ai_report_id")
    print(f"POST /v1/ai/dispatch_explain 202 ai_report_id={ai_report_id}")

    # 6) tick
    r_tick = session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 2}, timeout=timeout)
    if r_tick.status_code != 200:
        print(f"FAIL: POST tick -> {r_tick.status_code} {r_tick.text}", file=sys.stderr)
        return 1
    tick_data = r_tick.json()
    if tick_data.get("completed", 0) < 1:
        print(f"FAIL: tick completed < 1: {tick_data}", file=sys.stderr)
        return 1
    print(f"tick OK completed={tick_data.get('completed')}")

    # 7) GET ledger，断言新 decision
    r_ledger = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger.status_code != 200:
        print(f"FAIL: GET ledger -> {r_ledger.status_code}", file=sys.stderr)
        return 1
    data = r_ledger.json()
    decisions = data.get("decisions") or []
    if len(decisions) <= decisions_before:
        print(f"FAIL: decisions count expected > {decisions_before}, got {len(decisions)}", file=sys.stderr)
        return 1
    reroute = [d for d in decisions if d.get("decision_type") == "REROUTE_SUGGESTED"]
    if not reroute:
        print("FAIL: no decision with decision_type=REROUTE_SUGGESTED", file=sys.stderr)
        return 1
    summary = (reroute[-1].get("summary") or "")
    if "CHARGER_BUSY" not in summary or "INCIDENT_REPORTED" not in summary:
        print(f"FAIL: summary should contain dispatch_reason_codes: {summary!r}", file=sys.stderr)
        return 1
    if secret_ref in summary:
        print(f"FAIL: summary must not contain raw context_ref: {summary!r}", file=sys.stderr)
        return 1
    if "context_ref_hash=" not in summary:
        print(f"FAIL: summary should contain context_ref_hash (hash only): {summary!r}", file=sys.stderr)
        return 1
    print("PASS: ledger has REROUTE_SUGGESTED; summary has dispatch_reason_codes and context_ref_hash, no context_ref leak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
