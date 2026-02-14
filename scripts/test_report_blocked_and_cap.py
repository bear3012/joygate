#!/usr/bin/env python3
"""
M7 最小验证：POST /v1/incidents/report_blocked 幽灵桩校验 + 非法 incident_type + incidents 硬上限。
仅用 Python 标准库 urllib.request + json。
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_N = 210
DEFAULT_TIMEOUT_SEC = 3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M7 report_blocked: ghost charger, invalid type, cap")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL (default: %(default)s)")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="Number of POSTs for cap test (default: %(default)s)")
    p.add_argument("--timeout_sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="Request timeout (default: %(default)s)")
    return p.parse_args()


def post_report_blocked(base_url: str, body: dict, timeout: float) -> tuple[int, dict | None, str | None]:
    """POST /v1/incidents/report_blocked。返回 (status_code, parsed_json, raw_error)。"""
    url = base_url.rstrip("/") + "/v1/incidents/report_blocked"
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
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


def get_incidents(base_url: str, timeout: float) -> tuple[int, dict | None, str | None]:
    """GET /v1/incidents。返回 (status_code, parsed_json, raw_error)。"""
    url = base_url.rstrip("/") + "/v1/incidents"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
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
    args = parse_args()
    base = args.base_url
    timeout = args.timeout_sec
    n = args.n
    failed = False

    # 1) 幽灵桩
    code, js, err = post_report_blocked(
        base,
        {"charger_id": "charger-999", "incident_type": "BLOCKED"},
        timeout,
    )
    if err:
        print(f"ghost_charger: fail (error={err})")
        failed = True
    elif code != 400:
        print(f"ghost_charger: fail (status={code})")
        failed = True
    elif not (js and isinstance(js.get("detail"), str) and "unknown charger_id" in js["detail"]):
        print(f"ghost_charger: fail (detail missing 'unknown charger_id': {js})")
        failed = True
    else:
        print("ghost_charger: pass")

    # 2) 非法 incident_type
    code, js, err = post_report_blocked(
        base,
        {"charger_id": "charger-001", "incident_type": "GARBAGE"},
        timeout,
    )
    if err:
        print(f"invalid_type: fail (error={err})")
        failed = True
    elif code != 400:
        print(f"invalid_type: fail (status={code})")
        failed = True
    elif not (js and isinstance(js.get("detail"), str) and "invalid incident_type" in js["detail"]):
        print(f"invalid_type: fail (detail missing 'invalid incident_type': {js})")
        failed = True
    else:
        print("invalid_type: pass")

    # 3) 硬上限：n 次 POST 全 200 且含 incident_id，再 GET 列表长度 <= 200
    created_ok = 0
    for i in range(n):
        cid = f"charger-{(i % 10) + 1:03d}"
        code, js, err = post_report_blocked(base, {"charger_id": cid, "incident_type": "BLOCKED"}, timeout)
        if err:
            print(f"cap_test: created_ok={created_ok} list_len=? fail (POST {i+1} error={err})")
            failed = True
            break
        if code != 200:
            print(f"cap_test: created_ok={created_ok} list_len=? fail (POST {i+1} status={code})")
            failed = True
            break
        if not (js and isinstance(js.get("incident_id"), str)):
            print(f"cap_test: created_ok={created_ok} list_len=? fail (POST {i+1} no incident_id)")
            failed = True
            break
        created_ok += 1

    list_len = None
    if not failed and created_ok == n:
        code, js, err = get_incidents(base, timeout)
        if err:
            print(f"cap_test: created_ok={created_ok} list_len=? fail (GET error={err})")
            failed = True
        elif code != 200:
            print(f"cap_test: created_ok={created_ok} list_len=? fail (GET status={code})")
            failed = True
        elif not (js and isinstance(js.get("incidents"), list)):
            print(f"cap_test: created_ok={created_ok} list_len=? fail (GET incidents not list)")
            failed = True
        else:
            list_len = len(js["incidents"])
            if list_len > 200:
                print(f"cap_test: created_ok={created_ok} list_len={list_len} fail")
                failed = True
            else:
                print(f"cap_test: created_ok={created_ok} list_len={list_len} pass")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
