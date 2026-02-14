#!/usr/bin/env python3
"""
M13.1 T1：policy_suggest 入队 -> tick -> ledger 含 POLICY_SUGGESTED；
summary 含 context_ref_hash，不包含原始 context_ref。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.1 T1: policy_suggest -> tick -> ledger POLICY_SUGGESTED, no context_ref leak")
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

    r_rep = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": "charger-001", "incident_type": "BLOCKED"},
        timeout=timeout,
    )
    if r_rep.status_code != 200:
        print(f"FAIL: report_blocked -> {r_rep.status_code} {r_rep.text}", file=sys.stderr)
        return 1
    incident_id = r_rep.json().get("incident_id")
    print(f"report_blocked OK incident_id={incident_id}")

    secret_ref = "secret-policy-context-must-not-appear-67890"
    r_ps = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": incident_id, "context_ref": secret_ref},
        timeout=timeout,
    )
    if r_ps.status_code != 202:
        print(f"FAIL: POST policy_suggest -> {r_ps.status_code} {r_ps.text}", file=sys.stderr)
        return 1
    ai_report_id = r_ps.json().get("ai_report_id")
    print(f"POST /v1/ai/policy_suggest 202 ai_report_id={ai_report_id}")

    r_tick = session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 2}, timeout=timeout)
    if r_tick.status_code != 200:
        print(f"FAIL: tick -> {r_tick.status_code} {r_tick.text}", file=sys.stderr)
        return 1
    if r_tick.json().get("completed", 0) < 1:
        print(f"FAIL: tick completed < 1: {r_tick.json()}", file=sys.stderr)
        return 1
    print("tick OK")

    r_ledger = session.get(f"{base}/v1/audit/ledger", timeout=timeout)
    if r_ledger.status_code != 200:
        print(f"FAIL: GET ledger -> {r_ledger.status_code}", file=sys.stderr)
        return 1
    decisions = r_ledger.json().get("decisions") or []
    suggested = [d for d in decisions if d.get("decision_type") == "POLICY_SUGGESTED"]
    if not suggested:
        print("FAIL: no decision_type=POLICY_SUGGESTED in ledger", file=sys.stderr)
        return 1
    summary = suggested[-1].get("summary") or ""
    if secret_ref in summary:
        print(f"FAIL: summary must not contain raw context_ref: {summary!r}", file=sys.stderr)
        return 1
    if "context_ref_sha256=" not in summary:
        print(f"FAIL: summary should contain context_ref_sha256 (full): {summary!r}", file=sys.stderr)
        return 1
    print("PASS: ledger has POLICY_SUGGESTED; summary has context_ref_sha256, no context_ref leak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
