#!/usr/bin/env python3
"""
M8.1 Witness Voting HTTP 集成测试：验证路由/headers/返回码/字段口径（8 字段、不泄露 created_at/status_updated_at）
以及 witness 语义（allowlist、charger_state 校验、幂等、evidence_refs<=5、状态推进 EVIDENCE_CONFIRMED）。
使用 Python 标准库（urllib + subprocess），不依赖 requests。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen

DEFAULT_TIMEOUT = 5
HEALTH_CHECK_TIMEOUT = 5
PORT_RANGE_START = 8015
PORT_RANGE_END = 8099


def find_free_port() -> int:
    """找一个可用端口（8015-8099）"""
    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"no free port in range {PORT_RANGE_START}-{PORT_RANGE_END}")


def wait_for_health(base_url: str, timeout: float) -> bool:
    """等待服务健康：循环 GET /v1/snapshot 直到 200 或超时"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{base_url}/v1/snapshot", method="GET")
            with urlopen(req, timeout=2) as resp:
                if resp.getcode() == 200:
                    return True
        except (HTTPError, URLError, OSError, TimeoutError):
            pass
        time.sleep(0.2)
    return False


def get_json(opener, base_url: str, path: str, timeout: float) -> tuple[int, dict | None, str | None]:
    """GET JSON，返回 (status_code, parsed_json, raw_error)"""
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
    """POST JSON，返回 (status_code, parsed_json, raw_error)"""
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
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # 启动 uvicorn 子进程
    proc = None
    try:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "joygate.main:app", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=os.getcwd(),
        )

        # 等待健康检查
        if not wait_for_health(base_url, HEALTH_CHECK_TIMEOUT):
            proc.terminate()
            proc.wait(timeout=2)
            print(f"FAIL: service did not become healthy within {HEALTH_CHECK_TIMEOUT}s")
            return 1

        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))

        # 1) GET /bootstrap 建立 sandbox cookie
        code, js, err = get_json(opener, base_url, "/bootstrap", DEFAULT_TIMEOUT)
        if code != 200 or err:
            print(f"FAIL: GET /bootstrap -> {code}, error={err}")
            return 1

        # 2) POST /v1/incidents/report_blocked 创建 incident（evidence_refs 故意传 >5）
        code, data, err = post_json(
            opener,
            base_url,
            "/v1/incidents/report_blocked",
            {
                "charger_id": "charger-001",
                "incident_type": "BLOCKED",
                "snapshot_ref": "snapshot_test_001",
                "evidence_refs": ["ev:1", "ev:2", "ev:3", "ev:4", "ev:5", "ev:6", "ev:7"],
            },
            DEFAULT_TIMEOUT,
        )
        if code != 200 or err:
            print(f"FAIL: POST /v1/incidents/report_blocked -> {code}, error={err}, data={data}")
            return 1
        if not data or "incident_id" not in data:
            print(f"FAIL: POST /v1/incidents/report_blocked response missing incident_id: {data}")
            return 1
        incident_id = data["incident_id"]
        print(f"(1) POST /v1/incidents/report_blocked -> 200, incident_id={incident_id}")

        # 1.1) 验证 report_blocked 的 evidence_refs 上限（在 witness 投票之前）
        code, data_check, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err:
            print(f"FAIL: GET /v1/incidents (post-report) -> {code}, error={err}")
            return 1
        if not data_check or "incidents" not in data_check:
            print(f"FAIL: GET /v1/incidents response missing 'incidents': {data_check}")
            return 1
        incidents_check = data_check["incidents"]
        if not isinstance(incidents_check, list) or len(incidents_check) < 1:
            print(f"FAIL: GET /v1/incidents should return at least 1 incident")
            return 1
        item_check = None
        for inc in incidents_check:
            if inc.get("incident_id") == incident_id:
                item_check = inc
                break
        if not item_check:
            print(f"FAIL: incident_id {incident_id} not found in response")
            return 1
        evidence_refs_check = item_check.get("evidence_refs") or []
        if len(evidence_refs_check) > 5:
            print(f"FAIL: report_blocked evidence_refs should be <= 5, got {len(evidence_refs_check)}")
            return 1
        print("(1.1) GET /v1/incidents (post-report) -> evidence_refs<=5 confirmed")

        # 3) 非白名单 witness 应返回 403
        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {
                "incident_id": incident_id,
                "charger_id": "charger-001",
                "charger_state": "OCCUPIED",
            },
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "not_allowed"},
        )
        if code != 403:
            print(f"FAIL: non-allowlisted witness should return 403, got {code}, error={err}")
            return 1
        print("(2) POST /v1/witness/respond X-JoyKey=not_allowed -> 403")

        # 4) 非法 charger_state 应返回 400
        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {
                "incident_id": incident_id,
                "charger_id": "charger-001",
                "charger_state": "BAD_STATE",
            },
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "w1"},
        )
        if code not in (400, 422) or code >= 500:
            print(f"FAIL: invalid charger_state should return 400/422, got {code}, error={err}")
            return 1
        print(f"(3) POST /v1/witness/respond charger_state=BAD_STATE -> {code}")

        # 5) w1 首投（evidence_refs 传 >5）
        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {
                "incident_id": incident_id,
                "charger_id": "charger-001",
                "charger_state": "OCCUPIED",
                "points_event_id": "pe_w1_001",
                "evidence_refs": ["ev:w1_1", "ev:w1_2", "ev:w1_3", "ev:w1_4", "ev:w1_5", "ev:w1_6"],
            },
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "w1"},
        )
        if code != 204:
            print(f"FAIL: w1 first vote should return 204, got {code}, error={err}")
            return 1
        print("(4) POST /v1/witness/respond X-JoyKey=w1 -> 204")

        # 6) w1 重复投票（不同 points_event_id）
        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {
                "incident_id": incident_id,
                "charger_id": "charger-001",
                "charger_state": "OCCUPIED",
                "points_event_id": "pe_w1_002",
            },
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "w1"},
        )
        if code not in (200, 204) or code >= 400:
            print(f"FAIL: w1 duplicate vote should return 204/200, got {code}, error={err}")
            return 1
        print(f"(5) POST /v1/witness/respond X-JoyKey=w1 (duplicate) -> {code}")

        # 7) w2 第二票
        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {
                "incident_id": incident_id,
                "charger_id": "charger-001",
                "charger_state": "OCCUPIED",
                "points_event_id": "pe_w2_001",
            },
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "w2"},
        )
        if code != 204:
            print(f"FAIL: w2 vote should return 204, got {code}, error={err}")
            return 1
        print("(6) POST /v1/witness/respond X-JoyKey=w2 -> 204")

        # 8) GET /v1/incidents?incident_id=... 验证字段口径和状态
        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err:
            print(f"FAIL: GET /v1/incidents -> {code}, error={err}")
            return 1
        if not data or "incidents" not in data:
            print(f"FAIL: GET /v1/incidents response missing 'incidents': {data}")
            return 1
        incidents = data["incidents"]
        if not isinstance(incidents, list) or len(incidents) < 1:
            print(f"FAIL: GET /v1/incidents should return at least 1 incident, got {incidents}")
            return 1

        item = None
        for inc in incidents:
            if inc.get("incident_id") == incident_id:
                item = inc
                break
        if not item:
            print(f"FAIL: incident_id {incident_id} not found in response")
            return 1

        # 验证字段
        if item.get("incident_status") != "EVIDENCE_CONFIRMED":
            print(f"FAIL: incident_status should be EVIDENCE_CONFIRMED, got {item.get('incident_status')}")
            return 1

        evidence_refs = item.get("evidence_refs") or []
        if len(evidence_refs) > 5:
            print(f"FAIL: evidence_refs length should be <= 5, got {len(evidence_refs)}")
            return 1

        if "created_at" in item:
            print(f"FAIL: list_incidents must not expose created_at")
            return 1
        if "status_updated_at" in item:
            print(f"FAIL: list_incidents must not expose status_updated_at")
            return 1

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
        actual_keys = set(item.keys())
        if actual_keys != expected_keys:
            print(f"FAIL: IncidentItem keys mismatch: expected {expected_keys}, got {actual_keys}")
            return 1

        ai_insights = item.get("ai_insights") or []
        if not isinstance(ai_insights, list):
            print(f"FAIL: ai_insights should be a list, got {type(ai_insights)}")
            return 1
        tally_found = False
        for insight in ai_insights:
            if isinstance(insight, dict) and insight.get("insight_type") == "WITNESS_TALLY":
                tally_found = True
                break
        if not tally_found:
            print(f"FAIL: ai_insights should contain at least one WITNESS_TALLY, got {ai_insights}")
            return 1

        print("(7) GET /v1/incidents -> incident_status=EVIDENCE_CONFIRMED, evidence_refs<=5, 8 fields only, WITNESS_TALLY present")
        print("OK: witness voting HTTP semantics (8.1) passed.")
        return 0

    except Exception as e:
        print(f"FAIL: unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
