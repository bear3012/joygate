from __future__ import annotations

import os

# 预算=0，必须在 import 前设置，确保 joygate.config 读到
os.environ["JOYGATE_AI_DAILY_BUDGET_CALLS"] = "0"
os.environ["JOYGATE_AI_JOB_DEDUP_SECONDS"] = "0"

import joygate.store as store_mod  # noqa: E402
from joygate.store import JoyGateStore  # noqa: E402


def main() -> None:
    def fake_render(_: dict) -> bytes:
        return b"fakepng"

    def should_not_call_provider(*args, **kwargs):
        raise SystemExit("FAIL: provider should not be called when budget=0")

    store_mod.render_sim_snapshot_png = fake_render
    store_mod.generate_vision_audit_result = should_not_call_provider

    store = JoyGateStore()
    incident_id = store.report_blocked_incident("charger-001", "BLOCKED", snapshot_ref="snap_budget0")

    _ = store.create_vision_audit_job(incident_id)

    res = store.tick_ai_jobs(1)
    if res.get("processed") != 1 or res.get("completed") != 1:
        raise SystemExit(f"FAIL: unexpected tick result: {res}")

    jobs = store.list_ai_jobs()
    if len(jobs) != 1:
        raise SystemExit(f"FAIL: expected 1 job, got {len(jobs)}")
    job_status = jobs[0].get("ai_job_status")
    if job_status != "COMPLETED":
        raise SystemExit(f"FAIL: expected job COMPLETED, got {job_status!r}")

    internal_inc = None
    for r in store._incidents:  # type: ignore[attr-defined]
        if isinstance(r, dict) and r.get("incident_id") == incident_id:
            internal_inc = r
            break
    if not isinstance(internal_inc, dict):
        raise SystemExit("FAIL: incident not found")

    if internal_inc.get("incident_status") == "EVIDENCE_CONFIRMED":
        raise SystemExit("FAIL: incident should NOT be promoted to EVIDENCE_CONFIRMED when budget skipped")

    insights = internal_inc.get("ai_insights")
    if not isinstance(insights, list):
        raise SystemExit(f"FAIL: ai_insights missing, got={type(insights)}")
    found = False
    for it in insights:
        if isinstance(it, dict) and it.get("insight_type") == "VISION_AUDIT_RESULT":
            if it.get("summary") != "skipped due to budget":
                raise SystemExit(f"FAIL: unexpected summary: {it.get('summary')!r}")
            found = True
            break
    if not found:
        raise SystemExit("FAIL: VISION_AUDIT_RESULT insight not found")

    print("PASS: T4 daily budget=0 skips provider + no status promotion")


if __name__ == "__main__":
    main()
