#!/usr/bin/env python3
"""
验证 RESOLVED 后计时 + 写时清理 + low/high TTL 分级。
使用 requests + json。

运行前置条件：
- 需用环境变量启动服务：JOYGATE_TTL_RESOLVED_LOW_SECONDS=1、JOYGATE_TTL_RESOLVED_HIGH_SECONDS=5，
  以便 TTL 测试在数秒内完成（Case A 与 Case B 均依赖此配置）。
- --base_url 的端口须与已启动服务一致。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from _sandbox_client import get_bootstrapped_session

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SEC = 3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Verify RESOLVED-after TTL, write-time cleanup, low/high TTL. Server should use JOYGATE_TTL_RESOLVED_LOW_SECONDS=1 JOYGATE_TTL_RESOLVED_HIGH_SECONDS=5."
    )
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
    """POST /v1/incidents/update_status。返回 (status_code, parsed_json_or_none, raw_error)。"""
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


ALLOWED_INCIDENT_ITEM_KEYS = frozenset({
    "incident_id", "incident_type", "incident_status", "charger_id", "segment_id",
    "snapshot_ref", "evidence_refs", "ai_insights",
})
INTERNAL_KEYS_FORBIDDEN = frozenset({"created_at", "status_updated_at"})


def assert_incident_schema(item: dict) -> tuple[bool, str]:
    """
    校验 IncidentItem 严格仅含 8 个对外字段，且不包含 created_at / status_updated_at。
    返回 (True, "") 通过；(False, "fail(reason=...)") 失败。
    """
    if not isinstance(item, dict):
        return False, "fail(reason=item not a dict)"
    keys = set(item.keys())
    if keys != ALLOWED_INCIDENT_ITEM_KEYS:
        extra = keys - ALLOWED_INCIDENT_ITEM_KEYS
        missing = ALLOWED_INCIDENT_ITEM_KEYS - keys
        if extra:
            return False, f"fail(reason=forbidden or extra keys: {sorted(extra)})"
        if missing:
            return False, f"fail(reason=missing keys: {sorted(missing)})"
    for k in INTERNAL_KEYS_FORBIDDEN:
        if k in item:
            return False, f"fail(reason=internal key must not appear in API response: {k})"
    return True, ""


def get_incidents_by_id(
    session: requests.Session, base_url: str, incident_id: str, timeout: float
) -> tuple[int, list | None, str | None]:
    """GET /v1/incidents?incident_id=xxx。返回 (status_code, incidents 列表, raw_error)。"""
    url = base_url.rstrip("/") + "/v1/incidents?incident_id=" + incident_id
    try:
        resp = session.get(url, timeout=timeout)
        raw = resp.text
        try:
            js = json.loads(raw) if raw else None
            incidents = js.get("incidents", []) if isinstance(js, dict) else []
            return resp.status_code, incidents if isinstance(incidents, list) else [], None
        except json.JSONDecodeError:
            return resp.status_code, None, raw or None
    except requests.RequestException as e:
        return 0, None, str(e)


def get_incident_by_id(
    session: requests.Session, base_url: str, incident_id: str, timeout: float
) -> tuple[dict | None, str | None]:
    """
    调用 GET /v1/incidents?incident_id=xxx；列表为空返回 (None, None)；
    列表非空取 incidents[0]，经 assert_incident_schema 校验通过返回 (incident, None)，否则返回 (None, reason)。
    """
    code, incidents, err = get_incidents_by_id(session, base_url, incident_id, timeout)
    if err:
        return None, err
    if code != 200:
        return None, f"status={code}"
    if not incidents or len(incidents) == 0:
        return None, None
    item = incidents[0]
    ok, reason = assert_incident_schema(item)
    if not ok:
        return None, reason
    return item, None


def main() -> int:
    t0 = time.perf_counter()
    args = parse_args()
    base = args.base_url
    timeout = args.timeout_sec
    failed = False
    session = get_bootstrapped_session(base, timeout)

    # --- Case A: RESOLVED 后计时 + low TTL 过期 ---
    # A1: 创建 low retention 事件
    code, js, err = post_report_blocked(
        session, base, {"charger_id": "charger-001", "incident_type": "NO_PLUG"}, timeout
    )
    if err or code != 200 or not (js and isinstance(js.get("incident_id"), str)):
        print(f"ttl_from_resolved: fail (create error: {err or js})")
        failed = True
    else:
        id_a = js["incident_id"]
        time.sleep(2.0)
        code, _, err = post_update_status(
            session, base, {"incident_id": id_a, "incident_status": "RESOLVED"}, timeout
        )
        if err or code != 204:
            print(f"ttl_from_resolved: fail (update_status: {err or code})")
            failed = True
        else:
            post_report_blocked(session, base, {"charger_id": "charger-001", "incident_type": "BLOCKED"}, timeout)
            inc, err = get_incident_by_id(session, base, id_a, timeout)
            if err:
                print(f"ttl_from_resolved: fail ({err})")
                failed = True
            elif inc is None:
                print(f"ttl_from_resolved: fail (reason=expected incident still present after resolve+cleanup trigger)")
                failed = True
            elif inc.get("incident_status") != "RESOLVED":
                print(f"ttl_from_resolved: fail (reason=incident_status not RESOLVED)")
                failed = True
            else:
                print("ttl_from_resolved: pass")

        if not failed:
            time.sleep(1.2)
            post_report_blocked(session, base, {"charger_id": "charger-002", "incident_type": "BLOCKED"}, timeout)
            inc, err = get_incident_by_id(session, base, id_a, timeout)
            if err:
                print(f"low_ttl_expires: fail ({err})")
                failed = True
            elif inc is not None:
                print(f"low_ttl_expires: fail (reason=expected incident gone after low TTL)")
                failed = True
            else:
                print("low_ttl_expires: pass")

    # --- Case B: high TTL 先保留再过期（需服务端 JOYGATE_TTL_RESOLVED_LOW_SECONDS=1 JOYGATE_TTL_RESOLVED_HIGH_SECONDS=5）---
    code, js, err = post_report_blocked(
        session, base, {"charger_id": "charger-001", "incident_type": "BLOCKED"}, timeout
    )
    if err or code != 200 or not (js and isinstance(js.get("incident_id"), str)):
        print(f"high_ttl_kept_then_expires: fail (create: {err or js})")
        failed = True
    else:
        id_b = js["incident_id"]
        code, _, err = post_update_status(
            session, base, {"incident_id": id_b, "incident_status": "RESOLVED"}, timeout
        )
        if err or code != 204:
            print(f"high_ttl_kept_then_expires: fail (update_status: {err or code})")
            failed = True
        else:
            time.sleep(1.2)
            post_report_blocked(session, base, {"charger_id": "charger-002", "incident_type": "NO_PLUG"}, timeout)
            inc, err = get_incident_by_id(session, base, id_b, timeout)
            if err:
                print(f"high_ttl_kept_then_expires: fail ({err})")
                failed = True
            elif inc is None:
                print(f"high_ttl_kept_then_expires: fail (reason=expected high-retention incident still present at 1.2s)")
                failed = True
            elif inc.get("incident_status") != "RESOLVED":
                print(f"high_ttl_kept_then_expires: fail (reason=incident_status not RESOLVED)")
                failed = True
            else:
                time.sleep(4.2)
                post_report_blocked(session, base, {"charger_id": "charger-003", "incident_type": "OTHER"}, timeout)
                inc2, err2 = get_incident_by_id(session, base, id_b, timeout)
                if err2:
                    print(f"high_ttl_kept_then_expires: fail ({err2})")
                    failed = True
                elif inc2 is not None:
                    print(f"high_ttl_kept_then_expires: fail (reason=expected incident gone after high TTL)")
                    failed = True
                else:
                    print("high_ttl_kept_then_expires: pass")

    elapsed = time.perf_counter() - t0
    print(f"elapsed_sec={elapsed:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
