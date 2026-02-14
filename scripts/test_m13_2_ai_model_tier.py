#!/usr/bin/env python3
"""
M13.2 验收：Gemini 3.0 Pro/Flash 分流 + AI 入口 model_tier。
1) GET /bootstrap 拿 cookie
2) POST /v1/incidents/report_blocked -> incident_id
3) POST /v1/ai/vision_audit 传 model_tier=FLASH
4) POST /v1/ai/policy_suggest 不传 model_tier（默认 PRO）
5) POST /v1/reserve -> hold_id；POST /v1/ai/dispatch_explain 传 model_tier=PRO
6) POST /v1/ai_jobs/tick max_jobs=10
7) GET /v1/ai_jobs，断言 jobs 中三条 job 各自 model_tier 正确（FLASH / PRO / PRO）
8) 负例：POST /v1/ai/vision_audit model_tier=ULTRA -> 400
"""
from __future__ import annotations

import argparse
import sys

import requests

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
CHARGER_ID = "charger-001"
INCIDENT_TYPE = "BLOCKED"


def main() -> int:
    p = argparse.ArgumentParser(description="M13.2 ai_model_tier: FLASH/PRO + list_ai_jobs model_tier")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT)
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    # 1) bootstrap
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}")
        return 1

    # 2) report_blocked -> incident_id
    r = session.post(
        f"{base}/v1/incidents/report_blocked",
        json={"charger_id": CHARGER_ID, "incident_type": INCIDENT_TYPE},
        timeout=timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: report_blocked {r.status_code} {r.text[:300]}")
        return 1
    incident_id = r.json().get("incident_id")
    if not incident_id:
        print("FAIL: no incident_id")
        return 1

    # 3) vision_audit model_tier=FLASH
    r = session.post(
        f"{base}/v1/ai/vision_audit",
        json={"incident_id": incident_id, "model_tier": "FLASH"},
        timeout=timeout,
    )
    if r.status_code != 202:
        print(f"FAIL: vision_audit FLASH {r.status_code} {r.text[:300]}")
        return 1
    print("OK: POST /v1/ai/vision_audit model_tier=FLASH -> 202")

    # 4) policy_suggest 不传 model_tier（默认 PRO）
    r = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None},
        timeout=timeout,
    )
    if r.status_code != 202:
        print(f"FAIL: policy_suggest (no model_tier) {r.status_code} {r.text[:300]}")
        return 1
    print("OK: POST /v1/ai/policy_suggest (no model_tier) -> 202")

    # 5) reserve -> hold_id；dispatch_explain model_tier=PRO
    r = session.post(
        f"{base}/v1/reserve",
        json={"resource_type": "charger", "resource_id": "charger-002", "joykey": "jk_m132", "action": "HOLD"},
        timeout=timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: reserve {r.status_code} {r.text[:300]}")
        return 1
    hold_id = r.json().get("hold_id")
    if not hold_id:
        print("FAIL: no hold_id")
        return 1
    r = session.post(
        f"{base}/v1/ai/dispatch_explain",
        json={
            "hold_id": hold_id,
            "audience": "USER",
            "dispatch_reason_codes": ["CHARGER_BUSY"],
            "model_tier": "PRO",
        },
        timeout=timeout,
    )
    if r.status_code != 202:
        print(f"FAIL: dispatch_explain PRO {r.status_code} {r.text[:300]}")
        return 1
    print("OK: POST /v1/ai/dispatch_explain model_tier=PRO -> 202")

    # 6) tick
    r = session.post(f"{base}/v1/ai_jobs/tick", json={"max_jobs": 10}, timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: tick {r.status_code} {r.text[:300]}")
        return 1

    # 7) GET /v1/ai_jobs，断言三条 job 的 model_tier
    r = session.get(f"{base}/v1/ai_jobs", timeout=timeout)
    if r.status_code != 200:
        print(f"FAIL: GET /v1/ai_jobs {r.status_code}")
        return 1
    jobs = r.json().get("jobs") or []
    vision = [j for j in jobs if j.get("ai_job_type") == "VISION_AUDIT"]
    policy = [j for j in jobs if j.get("ai_job_type") == "POLICY_SUGGEST"]
    dispatch = [j for j in jobs if j.get("ai_job_type") == "DISPATCH_EXPLAIN"]
    if not any(j.get("model_tier") == "FLASH" for j in vision):
        print(f"FAIL: expected at least one VISION_AUDIT with model_tier=FLASH; vision={vision}")
        return 1
    if not any(j.get("model_tier") == "PRO" for j in policy):
        print(f"FAIL: expected at least one POLICY_SUGGEST with model_tier=PRO; policy={policy}")
        return 1
    if not any(j.get("model_tier") == "PRO" for j in dispatch):
        print(f"FAIL: expected at least one DISPATCH_EXPLAIN with model_tier=PRO; dispatch={dispatch}")
        return 1
    print("OK: GET /v1/ai_jobs jobs have model_tier FLASH (vision_audit) and PRO (policy_suggest, dispatch_explain)")
    print("    sample jobs:", [{"type": j.get("ai_job_type"), "model_tier": j.get("model_tier")} for j in jobs[-3:]])

    # 8) 负例：model_tier=ULTRA -> 400
    r = session.post(
        f"{base}/v1/ai/vision_audit",
        json={"incident_id": incident_id, "model_tier": "ULTRA"},
        timeout=timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: vision_audit model_tier=ULTRA expected 400, got {r.status_code} {r.text[:200]}")
        return 1
    detail = (r.json() or {}).get("detail", "")
    if "invalid model_tier" not in detail and "model_tier" not in detail.lower():
        print(f"FAIL: expected detail contains invalid model_tier, got detail={detail}")
        return 1
    print("OK: POST /v1/ai/vision_audit model_tier=ULTRA -> 400 invalid model_tier")

    print("OK: M13.2 ai_model_tier full pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
