#!/usr/bin/env python3
"""
M8.4 高风险 UNKNOWN_OCCUPANCY 认证分护栏测试。
使用 Python 标准库（urllib + subprocess），不依赖 requests。
M7.8：支持 --base_url（不自启 uvicorn）；自启时 is_port_free 选端口、失败分类（端口占用 vs 单实例锁）、打印 chosen_base_url。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen

DEFAULT_TIMEOUT = 5
HEALTH_POLL_TIMEOUT = 8.0
HEALTH_POLL_INTERVAL = 0.2
PORT_RANGE_START = 8015
PORT_RANGE_END = 8099
SINGLE_WORKER_LOCK_MARKER = "JoyGate requires --workers 1"


def is_port_free(host: str, port: int) -> bool:
    """用 socket bind 检测端口是否可用（bind 到 host:port）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.bind((host, port))
            return True
    except OSError:
        return False


def wait_for_health(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{base_url.rstrip('/')}/bootstrap", method="GET")
            with urlopen(req, timeout=2) as resp:
                if resp.getcode() == 200:
                    return True
        except (HTTPError, URLError, OSError, TimeoutError):
            pass
        time.sleep(HEALTH_POLL_INTERVAL)
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
    insights = item.get("ai_insights") or []
    if not any(isinstance(x, dict) and x.get("insight_type") == "WITNESS_TALLY" for x in insights):
        raise AssertionError("missing WITNESS_TALLY in ai_insights")


def _read_stderr_into_buffer(proc: subprocess.Popen, buffer: list[str], lock_seen: list[bool]) -> None:
    """后台线程：读 proc.stderr 到 buffer，若出现单实例锁文案则设 lock_seen[0]=True。"""
    try:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            s = (line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line))
            buffer.append(s)
            if SINGLE_WORKER_LOCK_MARKER in s:
                lock_seen[0] = True
                return
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="M8.4 certified points guard test (M7.8: --base_url / port robustness)")
    parser.add_argument("--base_url", type=str, default=None, help="使用已有服务，不自启 uvicorn")
    parser.add_argument("--port", type=int, default=None, help="自启时仅用该端口（否则从端口池选）")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    robots_config = {
        "vendor_alpha": [{"joykey": "a1", "points": 60}],
        "vendor_bravo": [{"joykey": "b1", "points": 60}],
        "vendor_charlie": [{"joykey": "c1", "points": 60}],
        "vendor_delta": [{"joykey": "d1", "points": 90}],
        "vendor_echo": [{"joykey": "e1", "points": 60}],
    }

    base_url: str | None = None
    mode: str
    proc = None
    try:
        if args.base_url:
            base_url = args.base_url.rstrip("/")
            mode = "external_base_url"
            print(f"chosen_base_url={base_url}")
            print(f"mode={mode}")
        else:
            mode = "spawned_uvicorn"
            env = os.environ.copy()
            env["PYTHONPATH"] = "src"
            env["JOYGATE_WITNESS_ROBOTS_JSON"] = json.dumps(robots_config, ensure_ascii=True)
            env["JOYGATE_WITNESS_VENDOR_DECAY_GAMMA"] = "0.5"
            env["JOYGATE_WITNESS_SLA_TIMEOUT_MINUTES"] = "0"
            env["JOYGATE_WITNESS_MIN_DISTINCT_VENDORS_RISKY"] = "3"
            env["JOYGATE_WITNESS_SCORE_REQUIRED_RISKY"] = "2.5"
            env["JOYGATE_WITNESS_MIN_MARGIN_RISKY"] = "1.0"
            env["JOYGATE_WITNESS_CERTIFIED_POINTS_THRESHOLD"] = "80"
            env["JOYGATE_WITNESS_MIN_CERTIFIED_SUPPORT_RISKY"] = "1"

            if args.port is not None:
                port_list = [args.port]
            else:
                port_list = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
                random.shuffle(port_list)
            host = "127.0.0.1"
            base_url = None
            spawned_ok = False
            for port in port_list:
                if not is_port_free(host, port):
                    continue
                base_url = f"http://{host}:{port}"
                proc = subprocess.Popen(
                    [
                        sys.executable, "-m", "uvicorn", "joygate.main:app",
                        "--host", host, "--port", str(port), "--workers", "1",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=repo_root,
                )
                stderr_buffer: list[str] = []
                lock_seen: list[bool] = [False]
                t = threading.Thread(target=_read_stderr_into_buffer, args=(proc, stderr_buffer, lock_seen), daemon=True)
                t.start()
                ready = False
                deadline = time.time() + HEALTH_POLL_TIMEOUT
                while time.time() < deadline:
                    if lock_seen[0]:
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            proc.kill()
                        proc = None
                        print("chosen_base_url=(none)")
                        print(f"mode={mode}")
                        print("FAIL: 单实例锁占用，已有 JoyGate 在运行。请关闭现有 JoyGate 或使用 --base_url http://127.0.0.1:端口")
                        return 1
                    if proc.poll() is not None:
                        try:
                            rest = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                            stderr_buffer.append(rest)
                        except Exception:
                            pass
                        if SINGLE_WORKER_LOCK_MARKER in "".join(stderr_buffer):
                            proc = None
                            print("chosen_base_url=(none)")
                            print(f"mode={mode}")
                            print("FAIL: 单实例锁占用，已有 JoyGate 在运行。请关闭现有 JoyGate 或使用 --base_url http://127.0.0.1:端口")
                            return 1
                        break
                    try:
                        req = Request(f"{base_url}/bootstrap", method="GET")
                        with urlopen(req, timeout=1) as resp:
                            if resp.getcode() == 200:
                                ready = True
                                spawned_ok = True
                                break
                    except (HTTPError, URLError, OSError, TimeoutError):
                        pass
                    time.sleep(HEALTH_POLL_INTERVAL)
                if spawned_ok:
                    break
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                proc = None
            if not spawned_ok:
                print("chosen_base_url=(none)")
                print(f"mode={mode}")
                print("FAIL: 未能启动服务：端口池不可用或健康检查超时，请先关闭占用端口的进程或使用 --base_url")
                return 1
            print(f"chosen_base_url={base_url}")
            print(f"mode={mode}")

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

        for joykey in ["a1", "b1", "c1"]:
            code, _, err = post_json(
                opener,
                base_url,
                "/v1/witness/respond",
                {"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "UNKNOWN_OCCUPANCY"},
                DEFAULT_TIMEOUT,
                extra_headers={"X-JoyKey": joykey},
            )
            if code != 204:
                print(f"FAIL: witness {joykey} UNKNOWN -> {code}, error={err}")
                return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (pre-certified) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id)
        if not item:
            print("FAIL: incident not found (pre-certified)")
            return 1
        assert_incident_shape(item)
        if item.get("incident_status") == "EVIDENCE_CONFIRMED":
            print("FAIL: should NOT confirm without certified support")
            return 1

        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "UNKNOWN_OCCUPANCY"},
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "d1"},
        )
        if code != 204:
            print(f"FAIL: witness d1 UNKNOWN -> {code}, error={err}")
            return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (confirm) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id)
        if not item:
            print("FAIL: incident not found (confirm)")
            return 1
        assert_incident_shape(item)
        if item.get("incident_status") != "EVIDENCE_CONFIRMED":
            print(f"FAIL: should confirm after certified support, got {item.get('incident_status')}")
            return 1

        print("OK: witness risky UNKNOWN certified points guard passed.")
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
