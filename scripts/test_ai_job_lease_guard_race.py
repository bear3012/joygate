#!/usr/bin/env python3
"""
测试 IN_PROGRESS lease 超时后重新入队时的竞态防护：
旧任务（拿旧 lease）在锁外跑完后回写应被 guard 跳过，不覆盖已被新 lease 领取的 job。
"""
from __future__ import annotations

import os
import threading
import time

# 在 import 任何 joygate 模块之前设置环境变量
os.environ["JOYGATE_AI_JOB_LEASE_SECONDS"] = "1"
os.environ["JOYGATE_AI_JOB_DEDUP_SECONDS"] = "0"

from joygate.store import JoyGateStore
import joygate.store as store_mod

# monkeypatch render_sim_snapshot_png：第 1 次 sleep 2 秒后返回；第 2 次及以后立刻返回
_render_call_count = [0]


def _patched_render_sim_snapshot_png(render_snapshot):
    _render_call_count[0] += 1
    if _render_call_count[0] == 1:
        time.sleep(2)
    return b"fakepng"


store_mod.render_sim_snapshot_png = _patched_render_sim_snapshot_png


def _patched_generate_vision_audit_result(provider, incident_rec, image_png_bytes=None):
    return {
        "summary": "lease guard test",
        "confidence": 70,
        "obstacle_type": "UNKNOWN",
        "sample_index": 0,
    }


store_mod.generate_vision_audit_result = _patched_generate_vision_audit_result

# --- 流程 ---
store = JoyGateStore()
incident_id = store.report_blocked_incident(
    "charger-001", "BLOCKED", snapshot_ref="snap_race"
)
job_view = store.create_vision_audit_job(incident_id)
ai_job_id = job_view.get("ai_job_id")

result_a = [None]
result_b = [None]


def thread_a():
    result_a[0] = store.tick_ai_jobs(1)


def thread_b():
    result_b[0] = store.tick_ai_jobs(1)


thread_a_obj = threading.Thread(target=thread_a)
thread_a_obj.start()
time.sleep(1.2)
thread_b_obj = threading.Thread(target=thread_b)
thread_b_obj.start()
thread_a_obj.join()
thread_b_obj.join()

print("tick A:", result_a[0])
print("tick B:", result_b[0])
jobs = store.list_ai_jobs()
print("list_ai_jobs:", jobs)

job = next((j for j in jobs if j.get("ai_job_id") == ai_job_id), None)
if job is None:
    print("job not found in list_ai_jobs")
    raise SystemExit(1)
status = job.get("ai_job_status")
print("job final ai_job_status:", status)
if status not in ("COMPLETED", "FAILED"):
    raise SystemExit(1)
print("PASS")
