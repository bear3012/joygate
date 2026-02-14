from __future__ import annotations

import os
import time

# 确保不走 dedup，且 env 在 import 前生效
os.environ["JOYGATE_AI_JOB_DEDUP_SECONDS"] = "0"

from joygate.store import JoyGateStore  # noqa: E402


def main() -> None:
    store = JoyGateStore()
    base = time.time()

    # 先造一些轨迹
    store.record_segment_passed("cell_1_1", base + 1, "robotA", "sim")
    store.record_segment_passed("cell_2_2", base + 2, "robotA", "sim")
    store.record_segment_passed("cell_3_3", base + 3, "robotB", "sim")

    incident_id = store.report_blocked_incident("charger-001", "BLOCKED", snapshot_ref="snap_freeze")

    job_view = store.create_vision_audit_job(incident_id)
    job_id = job_view.get("ai_job_id")
    if not isinstance(job_id, str) or not job_id:
        raise SystemExit(f"FAIL: bad job_id: {job_id!r}")

    job = store._ai_jobs.get(job_id)  # type: ignore[attr-defined]
    if not isinstance(job, dict):
        raise SystemExit("FAIL: job not found in store._ai_jobs")

    rs = job.get("render_snapshot")
    if not isinstance(rs, dict):
        raise SystemExit("FAIL: render_snapshot missing")
    frozen = rs.get("robot_tracks")
    if not isinstance(frozen, dict):
        raise SystemExit("FAIL: render_snapshot.robot_tracks missing")

    frozen_before = {k: list(v) for k, v in frozen.items() if isinstance(v, list)}

    # 之后继续写轨迹（应只影响 store._robot_tracks，不影响 job 内 frozen copy）
    store.record_segment_passed("cell_9_9", base + 9, "robotA", "sim")
    store.record_segment_passed("cell_10_10", base + 10, "robotC", "sim")

    job2 = store._ai_jobs.get(job_id)  # type: ignore[attr-defined]
    rs2 = job2.get("render_snapshot") if isinstance(job2, dict) else None
    frozen2 = rs2.get("robot_tracks") if isinstance(rs2, dict) else None
    if not isinstance(frozen2, dict):
        raise SystemExit("FAIL: render_snapshot.robot_tracks missing after mutation")

    frozen_after = {k: list(v) for k, v in frozen2.items() if isinstance(v, list)}

    if frozen_after != frozen_before:
        raise SystemExit(f"FAIL: frozen robot_tracks mutated: before={frozen_before} after={frozen_after}")

    print("PASS: T2 render_snapshot robot_tracks frozen snapshot")


if __name__ == "__main__":
    main()
