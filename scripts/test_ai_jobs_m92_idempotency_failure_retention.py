#!/usr/bin/env python3
"""
M9.2 AI Jobs 加固测试：幂等创建 / list 输出收口 / tick 失败语义 / 留存清理。
使用 Python 标准库（urllib + subprocess），不依赖 requests。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen

DEFAULT_TIMEOUT = 5
HEALTH_CHECK_TIMEOUT = 5
PORT_RANGE_START = 8015
PORT_RANGE_END = 8099
PORT_MAX_ATTEMPTS = 20


def wait_for_health(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{base_url}/bootstrap", method="GET")
            with urlopen(req, timeout=2) as resp:
                if resp.getcode() == 200:
                    return True
        except (HTTPError, URLError, OSError, TimeoutError):
            pass
        time.sleep(0.2)
    return False


def get_json(opener, base_url: str, path: str, timeout: float) -> tuple[int, dict | None, str | None]:
    url = base_url.rstrip("/") + path
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return e.code, None, raw
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def post_json(
    opener, base_url: str, path: str, body: dict, timeout: float, extra_headers: dict | None = None
) -> tuple[int, dict | None, str | None]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=data, method="POST", headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return e.code, None, raw
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    proc = None
    try:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["JOYGATE_MAX_INCIDENTS"] = "1"
        env["JOYGATE_AI_JOB_RETENTION_SECONDS"] = "1"

        ports = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
        random.shuffle(ports)
        base_url = None
        for port in ports[:PORT_MAX_ATTEMPTS]:
            base_url = f"http://127.0.0.1:{port}"
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "joygate.main:app", "--port", str(port), "--workers", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=repo_root,
            )
            if wait_for_health(base_url, HEALTH_CHECK_TIMEOUT):
                break
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            proc = None
        else:
            print(f"FAIL: service did not become healthy within {HEALTH_CHECK_TIMEOUT}s")
            return 1

        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))

        code, _, err = get_json(opener, base_url, "/bootstrap", DEFAULT_TIMEOUT)
        if code != 200:
            print(f"FAIL: GET /bootstrap -> {code}, err={err}")
            return 1

        # 幂等创建
        report_body = {
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "snap_m92_a",
        }
        code, data, err = post_json(opener, base_url, "/v1/incidents/report_blocked", report_body, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict) or not data.get("incident_id"):
            print(f"FAIL: report_blocked A -> {code}, data={data}, err={err}")
            return 1
        incident_a = data["incident_id"]

        code, data, err = post_json(
            opener, base_url, "/v1/ai_jobs/vision_audit", {"incident_id": incident_a}, DEFAULT_TIMEOUT
        )
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: vision_audit A#1 -> {code}, data={data}, err={err}")
            return 1
        job_a_1 = data.get("ai_job_id")
        if not job_a_1:
            print(f"FAIL: missing ai_job_id A#1: {data}")
            return 1

        code, data, err = post_json(
            opener, base_url, "/v1/ai_jobs/vision_audit", {"incident_id": incident_a}, DEFAULT_TIMEOUT
        )
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: vision_audit A#2 -> {code}, data={data}, err={err}")
            return 1
        job_a_2 = data.get("ai_job_id")
        if job_a_1 != job_a_2:
            print(f"FAIL: idempotency broken: job_a_1={job_a_1}, job_a_2={job_a_2}")
            return 1

        code, data, err = get_json(opener, base_url, "/v1/ai_jobs", DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: GET /v1/ai_jobs -> {code}, data={data}, err={err}")
            return 1
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            print(f"FAIL: jobs invalid: {data}")
            return 1
        jobs_a = [j for j in jobs if isinstance(j, dict) and j.get("incident_id") == incident_a]
        if len(jobs_a) != 1:
            print(f"FAIL: incident A jobs count != 1: {jobs_a}")
            return 1

        # list 输出收口
        expected_keys = {"ai_job_id", "ai_job_type", "ai_job_status", "incident_id"}
        for j in jobs:
            if not isinstance(j, dict) or set(j.keys()) != expected_keys:
                print(f"FAIL: job keys mismatch: {j}")
                return 1

        # tick 找不到 incident -> FAILED
        report_body = {
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "snap_m92_b",
        }
        code, data, err = post_json(opener, base_url, "/v1/incidents/report_blocked", report_body, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict) or not data.get("incident_id"):
            print(f"FAIL: report_blocked B -> {code}, data={data}, err={err}")
            return 1

        code, data, err = post_json(opener, base_url, "/v1/ai_jobs/tick", {"max_jobs": 10}, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: tick -> {code}, data={data}, err={err}")
            return 1

        code, data, err = get_json(opener, base_url, "/v1/ai_jobs", DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: GET /v1/ai_jobs after tick -> {code}, data={data}, err={err}")
            return 1
        jobs = data.get("jobs") or []
        job_a = next((j for j in jobs if j.get("ai_job_id") == job_a_1), None)
        if not job_a or job_a.get("ai_job_status") != "FAILED":
            print(f"FAIL: job A should be FAILED: {job_a}")
            return 1

        # 留存清理
        report_body = {
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "snap_m92_c",
        }
        code, data, err = post_json(opener, base_url, "/v1/incidents/report_blocked", report_body, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict) or not data.get("incident_id"):
            print(f"FAIL: report_blocked C -> {code}, data={data}, err={err}")
            return 1
        incident_c = data["incident_id"]

        code, data, err = post_json(
            opener, base_url, "/v1/ai_jobs/vision_audit", {"incident_id": incident_c}, DEFAULT_TIMEOUT
        )
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: vision_audit C -> {code}, data={data}, err={err}")
            return 1
        job_c = data.get("ai_job_id")
        if not job_c:
            print(f"FAIL: missing ai_job_id C: {data}")
            return 1

        code, data, err = post_json(opener, base_url, "/v1/ai_jobs/tick", {"max_jobs": 10}, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: tick C -> {code}, data={data}, err={err}")
            return 1

        time.sleep(1.2)

        report_body = {
            "charger_id": "charger-001",
            "incident_type": "BLOCKED",
            "snapshot_ref": "snap_m92_d",
        }
        code, data, err = post_json(opener, base_url, "/v1/incidents/report_blocked", report_body, DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict) or not data.get("incident_id"):
            print(f"FAIL: report_blocked D -> {code}, data={data}, err={err}")
            return 1
        incident_d = data["incident_id"]

        code, data, err = post_json(
            opener, base_url, "/v1/ai_jobs/vision_audit", {"incident_id": incident_d}, DEFAULT_TIMEOUT
        )
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: vision_audit D -> {code}, data={data}, err={err}")
            return 1
        job_d = data.get("ai_job_id")
        if not job_d:
            print(f"FAIL: missing ai_job_id D: {data}")
            return 1

        code, data, err = get_json(opener, base_url, "/v1/ai_jobs", DEFAULT_TIMEOUT)
        if code != 200 or not isinstance(data, dict):
            print(f"FAIL: GET /v1/ai_jobs retention -> {code}, data={data}, err={err}")
            return 1
        jobs = data.get("jobs") or []
        ids = {j.get("ai_job_id") for j in jobs if isinstance(j, dict)}
        if job_c in ids:
            print(f"FAIL: retention cleanup failed, job_c still present: {job_c}")
            return 1
        if job_d not in ids:
            print(f"FAIL: active job_d missing: {job_d}")
            return 1

        print("OK: ai_jobs M9.2 idempotency+failure+retention passed.")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
