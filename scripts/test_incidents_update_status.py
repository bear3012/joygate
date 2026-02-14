#!/usr/bin/env python3
"""
M7.1 最小验证：POST /v1/incidents/update_status 合法状态流转、非法枚举、非法流转、404。
使用 requests + json。
"""
from __future__ import annotations

import argparse
import json
import sys

import requests

from _sandbox_client import get_bootstrapped_session

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SEC = 3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M7.1 update_status: create, RESOLVED, GET, invalid status/transition, 404")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL (default: %(default)s)")
    p.add_argument("--timeout_sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="Request timeout (default: %(default)s)")
    return p.parse_args()


def post_report_blocked(
    session: requests.Session, base_url: str, body: dict, timeout: float
) -> tuple[int, dict | None, str | None]:
    """POST /v1/incidents/report_blocked。返回 (status_code, parsed_json, raw_error)。"""
    url = base_url.rstrip("/") + "/v1/incidents/report_blocked"
    try:
        resp = session.post(url, json=body, timeout=timeout)
        raw = resp.text
        try:
            return resp.status_code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return resp.status_code, None, raw or None
    except requests.RequestException as e:
        return 0, None, str(e)


def post_update_status(
    session: requests.Session, base_url: str, body: dict, timeout: float
) -> tuple[int, dict | None, str | None]:
    """POST /v1/incidents/update_status。返回 (status_code, parsed_json_or_none, raw_error)。204 无 body。"""
    url = base_url.rstrip("/") + "/v1/incidents/update_status"
    try:
        resp = session.post(url, json=body, timeout=timeout)
        raw = resp.text
        if not raw:
            return resp.status_code, None, None
        try:
            return resp.status_code, json.loads(raw), None
        except json.JSONDecodeError:
            return resp.status_code, None, raw or None
    except requests.RequestException as e:
        return 0, None, str(e)


def get_incidents(
    session: requests.Session, base_url: str, incident_status: str | None, timeout: float
) -> tuple[int, dict | None, str | None]:
    """GET /v1/incidents[?incident_status=...]。返回 (status_code, parsed_json, raw_error)。"""
    url = base_url.rstrip("/") + "/v1/incidents"
    if incident_status:
        url += "?incident_status=" + incident_status
    try:
        resp = session.get(url, timeout=timeout)
        raw = resp.text
        try:
            return resp.status_code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return resp.status_code, None, raw or None
    except requests.RequestException as e:
        return 0, None, str(e)


def main() -> int:
    args = parse_args()
    base = args.base_url
    timeout = args.timeout_sec
    failed = False

    session = get_bootstrapped_session(base, timeout)

    # 1) POST report_blocked 创建一条，拿 incident_id
    code, js, err = post_report_blocked(
        session, base, {"charger_id": "charger-001", "incident_type": "BLOCKED"}, timeout
    )
    if err:
        print(f"create: fail (error={err})")
        return 1
    if code != 200 or not (js and isinstance(js.get("incident_id"), str)):
        print(f"create: fail (status={code} body={js})")
        return 1
    incident_id = js["incident_id"]
    print(f"create: pass incident_id={incident_id}")

    # 2) POST update_status 改成 RESOLVED -> 204
    code, _, err = post_update_status(
        session, base, {"incident_id": incident_id, "incident_status": "RESOLVED"}, timeout
    )
    if err:
        print(f"update_to_resolved: fail (error={err})")
        failed = True
    elif code != 204:
        print(f"update_to_resolved: fail (status={code}, expected 204)")
        failed = True
    else:
        print("update_to_resolved: pass")

    # 3) GET /v1/incidents?incident_status=RESOLVED 至少 1 条
    if not failed:
        code, js, err = get_incidents(session, base, "RESOLVED", timeout)
        if err:
            print(f"get_resolved: fail (error={err})")
            failed = True
        elif code != 200:
            print(f"get_resolved: fail (status={code})")
            failed = True
        elif not (js and isinstance(js.get("incidents"), list) and len(js["incidents"]) >= 1):
            print(f"get_resolved: fail (incidents len={len(js.get('incidents', [])) if js else 0})")
            failed = True
        else:
            print("get_resolved: pass")

    # 4) 非法 incident_status GARBAGE -> 400 且 detail 包含 GARBAGE
    code, js, err = post_update_status(
        session, base, {"incident_id": incident_id, "incident_status": "GARBAGE"}, timeout
    )
    if err:
        print(f"invalid_status: fail (error={err})")
        failed = True
    elif code != 400:
        print(f"invalid_status: fail (status={code}, expected 400)")
        failed = True
    elif not (js and isinstance(js.get("detail"), str) and "GARBAGE" in js["detail"]):
        print(f"invalid_status: fail (detail missing GARBAGE: {js})")
        failed = True
    else:
        print("invalid_status: pass")

    # 5) 非法流转：RESOLVED -> OPEN -> 400 且 detail 包含 transition
    code, js, err = post_update_status(
        session, base, {"incident_id": incident_id, "incident_status": "OPEN"}, timeout
    )
    if err:
        print(f"invalid_transition: fail (error={err})")
        failed = True
    elif code != 400:
        print(f"invalid_transition: fail (status={code}, expected 400)")
        failed = True
    elif not (js and isinstance(js.get("detail"), str) and "transition" in js["detail"]):
        print(f"invalid_transition: fail (detail missing transition: {js})")
        failed = True
    else:
        print("invalid_transition: pass")

    # 6) 不存在 incident_id -> 404
    code, js, err = post_update_status(
        session, base, {"incident_id": "not found", "incident_status": "RESOLVED"}, timeout
    )
    if err:
        print(f"not_found: fail (error={err})")
        failed = True
    elif code != 404:
        print(f"not_found: fail (status={code}, expected 404)")
        failed = True
    elif not (js and isinstance(js.get("detail"), str) and "not found" in js["detail"].lower()):
        print(f"not_found: fail (detail missing not found: {js})")
        failed = True
    else:
        print("not_found: pass")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
