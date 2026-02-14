from __future__ import annotations

import os
import time

# dedup=1s，且给足预算确保能完成一次 job
os.environ["JOYGATE_AI_JOB_DEDUP_SECONDS"] = "1"
os.environ["JOYGATE_AI_DAILY_BUDGET_CALLS"] = "10"

import joygate.store as store_mod  # noqa: E402
from joygate.store import JoyGateStore  # noqa: E402


def main() -> None:
    # monkeypatch：避免真实渲染/真实 provider
    def fake_render(_: dict) -> bytes:
        return b"fakepng"

    def fake_provider(provider: str, incident_rec: dict, png_bytes: bytes) -> dict:
        return {
            "summary": "ok",
            "confidence": 0.9,
            "obstacle_type": "OTHER",
            "sample_index": 0,
        }

    store_mod.render_sim_snapshot_png = fake_render
    store_mod.generate_vision_audit_result = fake_provider

    store = JoyGateStore()
    incident_id = store.report_blocked_incident("charger-001", "BLOCKED", snapshot_ref="snap_dedup")

    j1 = store.create_vision_audit_job(incident_id)
    job1_id = j1.get("ai_job_id")
    if not isinstance(job1_id, str) or not job1_id:
        raise SystemExit("FAIL: job1 id missing")

    r1 = store.tick_ai_jobs(1)
    if r1.get("completed") != 1:
        raise SystemExit(f"FAIL: first tick did not complete: {r1}")

    # 窗口内再次创建，应复用 terminal job（同 ai_job_id/ai_report_id）
    j2 = store.create_vision_audit_job(incident_id)
    if j2.get("ai_job_id") != j1.get("ai_job_id") or j2.get("ai_report_id") != j1.get("ai_report_id"):
        raise SystemExit(f"FAIL: expected dedup reuse within window, j1={j1} j2={j2}")

    # 超过窗口后应新建
    time.sleep(1.2)
    j3 = store.create_vision_audit_job(incident_id)
    if j3.get("ai_job_id") == j1.get("ai_job_id"):
        raise SystemExit(f"FAIL: expected new job after dedup window, j3={j3}")

    print("PASS: T5 terminal dedup reuses within window, creates new after window")


if __name__ == "__main__":
    main()
