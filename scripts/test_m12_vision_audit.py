#!/usr/bin/env python3
"""
M12A-1 最小可复现：POST report_blocked -> POST /v1/ai/vision_audit -> 202 ->
tick -> GET incidents?incident_id=...，断言 ai_insights 含 VISION_AUDIT_REQUESTED 与 VISION_AUDIT_RESULT。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M12 vision_audit 202 + tick + ai_insights")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout_sec", type=float, default=15.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec
    session = requests.Session()

    # 1) GET bootstrap
    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK, cookie set")

    # 2) POST /v1/incidents/report_blocked
    report_body = {
        "charger_id": "charger-001",
        "incident_type": "BLOCKED",
        "snapshot_ref": "snap_m12",
        "evidence_refs": ["ev_m12_1"],
    }
    r_report = session.post(f"{base}/v1/incidents/report_blocked", json=report_body, timeout=timeout)
    if r_report.status_code != 200:
        print(f"FAIL: POST /v1/incidents/report_blocked -> {r_report.status_code} {r_report.text}", file=sys.stderr)
        return 1
    try:
        report_data = r_report.json()
    except Exception as e:
        print(f"FAIL: report_blocked response not JSON: {e}", file=sys.stderr)
        return 1
    incident_id = report_data.get("incident_id")
    if not incident_id:
        print("FAIL: report_blocked missing incident_id", file=sys.stderr)
        return 1
    print(f"POST /v1/incidents/report_blocked 200 incident_id={incident_id}")

    # 3) POST /v1/ai/vision_audit -> 202 (ai_report_id + status)
    vision_body = {
        "incident_id": incident_id,
        "snapshot_ref": "snap_m12",
        "evidence_refs": ["ev_m12_1"],
    }
    r_vision = session.post(f"{base}/v1/ai/vision_audit", json=vision_body, timeout=timeout)
    if r_vision.status_code != 202:
        print(f"FAIL: POST /v1/ai/vision_audit -> {r_vision.status_code} {r_vision.text}", file=sys.stderr)
        return 1
    try:
        vision_data = r_vision.json()
    except Exception as e:
        print(f"FAIL: vision_audit response not JSON: {e}", file=sys.stderr)
        return 1
    ai_report_id = vision_data.get("ai_report_id")
    status = vision_data.get("status")
    if not ai_report_id or status != "ACCEPTED":
        print(f"FAIL: vision_audit 202 missing ai_report_id or status != ACCEPTED: {vision_data}", file=sys.stderr)
        return 1
    print(f"POST /v1/ai/vision_audit 202 ai_report_id={ai_report_id} status={status}")
    print(f"202 body: {vision_data}")

    # 4) POST /v1/ai_jobs/tick
    r_tick = session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 1}, timeout=timeout)
    if r_tick.status_code != 200:
        print(f"FAIL: POST /v1/ai_jobs/tick -> {r_tick.status_code} {r_tick.text}", file=sys.stderr)
        return 1
    try:
        tick_data = r_tick.json()
    except Exception as e:
        print(f"FAIL: tick response not JSON: {e}", file=sys.stderr)
        return 1
    print(f"POST /v1/ai_jobs/tick 200: {tick_data}")
    if tick_data.get("processed") != 1 or tick_data.get("completed") != 1:
        print(f"FAIL: tick processed/completed expected 1/1: {tick_data}", file=sys.stderr)
        return 1

    # 5) GET /v1/incidents?incident_id=...
    r_inc = session.get(f"{base}/v1/incidents", params={"incident_id": incident_id}, timeout=timeout)
    if r_inc.status_code != 200:
        print(f"FAIL: GET /v1/incidents -> {r_inc.status_code} {r_inc.text}", file=sys.stderr)
        return 1
    try:
        inc_data = r_inc.json()
    except Exception as e:
        print(f"FAIL: incidents response not JSON: {e}", file=sys.stderr)
        return 1
    incidents = inc_data.get("incidents")
    if not isinstance(incidents, list) or len(incidents) != 1:
        print(f"FAIL: incidents list invalid: {incidents!r}", file=sys.stderr)
        return 1
    inc = incidents[0]
    ai_insights = inc.get("ai_insights") or []
    print(f"GET /v1/incidents 200 ai_insights count={len(ai_insights)}")
    print(f"incident ai_insights: {ai_insights}")

    has_requested = any(
        isinstance(x, dict) and x.get("insight_type") == "VISION_AUDIT_REQUESTED" for x in ai_insights
    )
    has_result = any(
        isinstance(x, dict) and x.get("insight_type") == "VISION_AUDIT_RESULT" for x in ai_insights
    )
    if not has_requested:
        print("FAIL: ai_insights missing VISION_AUDIT_REQUESTED", file=sys.stderr)
        return 1
    if not has_result:
        print("FAIL: ai_insights missing VISION_AUDIT_RESULT", file=sys.stderr)
        return 1
    req_item = next(x for x in ai_insights if isinstance(x, dict) and x.get("insight_type") == "VISION_AUDIT_REQUESTED")
    res_item = next(x for x in ai_insights if isinstance(x, dict) and x.get("insight_type") == "VISION_AUDIT_RESULT")
    if req_item.get("ai_report_id") != ai_report_id or res_item.get("ai_report_id") != ai_report_id:
        print(f"FAIL: ai_report_id mismatch requested={req_item.get('ai_report_id')} result={res_item.get('ai_report_id')} expected={ai_report_id}", file=sys.stderr)
        return 1

    print("OK M12 vision_audit test passed: 202 + tick + ai_insights VISION_AUDIT_REQUESTED + VISION_AUDIT_RESULT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
