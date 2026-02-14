#!/usr/bin/env python3
"""
M8.x Witness SLA 超时降级测试（UNDER_OBSERVATION + VISION_AUDIT_REQUESTED）。
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


def find_incident(items: list[dict], incident_id: str) -> dict | None:
    for inc in items:
        if inc.get("incident_id") == incident_id:
            return inc
    return None


def assert_incident_shape(item: dict) -> None:
    expected_keys = {
        "incident_id",
        "incident_type",
        "incident_status",
        "charger_id",
        "segment_id",
        "snapshot_ref",
        "evidence_refs",
        "ai_insights",
    }
    if set(item.keys()) != expected_keys:
        raise AssertionError(f"incident keys mismatch: {set(item.keys())}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    proc = None
    try:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["JOYGATE_WITNESS_SLA_TIMEOUT_MINUTES"] = "0.01"
        env["JOYGATE_WITNESS_SCORE_REQUIRED"] = "999"
        env["JOYGATE_WITNESS_SCORE_REQUIRED_SINGLE_VENDOR"] = "999"

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
        if code != 200 or err:
            print(f"FAIL: GET /bootstrap -> {code}, error={err}")
            return 1

        code, data, err = post_json(
            opener,
            base_url,
            "/v1/incidents/report_blocked",
            {"charger_id": "charger-001", "incident_type": "BLOCKED"},
            DEFAULT_TIMEOUT,
        )
        if code != 200 or err or not data or "incident_id" not in data:
            print(f"FAIL: report_blocked -> {code}, error={err}, data={data}")
            return 1
        incident_id = data["incident_id"]

        time.sleep(1.0)

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id)
        if not item:
            print("FAIL: incident not found")
            return 1
        assert_incident_shape(item)
        if item.get("incident_status") != "UNDER_OBSERVATION":
            print(f"FAIL: incident_status expected UNDER_OBSERVATION, got {item.get('incident_status')}")
            return 1
        insights = item.get("ai_insights") or []
        if not any(isinstance(x, dict) and x.get("insight_type") == "VISION_AUDIT_REQUESTED" for x in insights):
            print("FAIL: missing VISION_AUDIT_REQUESTED in ai_insights")
            return 1

        print("OK: witness SLA timeout downgrade + vision audit requested passed.")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
