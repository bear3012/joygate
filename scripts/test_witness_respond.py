#!/usr/bin/env python3
"""
M8 witness 桩占用投票验收：bootstrap cookie -> report_blocked -> 两次 witness -> 校验 EVIDENCE_CONFIRMED + WITNESS_TALLY；
重复投票 204 且 tally 不重复计数。仅用 Python 标准库（urllib + cookiejar）。
"""
from __future__ import annotations

import argparse
import json
import sys
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_TIMEOUT = 10


def parse_args():
    p = argparse.ArgumentParser(description="M8 witness/respond: bootstrap, report_blocked, 2 votes, idempotent")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Request timeout")
    return p.parse_args()


def get_json(opener, base_url: str, path: str, timeout: float) -> tuple[int, dict | None]:
    url = base_url.rstrip("/") + path
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else None
    except (URLError, OSError, TimeoutError):
        return 0, None


def post_json(
    opener, base_url: str, path: str, body: dict, timeout: float, extra_headers: dict | None = None
) -> tuple[int, dict | None]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=data, method="POST", headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else None
    except (URLError, OSError, TimeoutError):
        return 0, None


def main() -> int:
    args = parse_args()
    base = args.base_url
    timeout = args.timeout

    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    # 1) GET /bootstrap 获取 cookie
    code, js = get_json(opener, base, "/bootstrap", timeout)
    if code != 200 or not js:
        print("FAIL: GET /bootstrap ->", code, js)
        return 1
    print("(1) GET /bootstrap ->", code, js)

    # 2) POST /v1/incidents/report_blocked 创建 incident
    code, data = post_json(
        opener, base, "/v1/incidents/report_blocked",
        {"charger_id": "charger-001", "incident_type": "BLOCKED"},
        timeout,
    )
    if code != 200 or not data:
        print("FAIL: report_blocked ->", code, data)
        return 1
    incident_id = data.get("incident_id")
    if not incident_id:
        print("FAIL: report_blocked did not return incident_id", data)
        return 1
    print("(2) POST /v1/incidents/report_blocked ->", code, "incident_id=", incident_id)

    # (3a) w1 首投（不带 points_event_id）
    witness_body = {"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "OCCUPIED"}
    code, _ = post_json(
        opener, base, "/v1/witness/respond", witness_body, timeout,
        extra_headers={"X-JoyKey": "w1"},
    )
    if code != 204:
        print("FAIL: (3a) witness w1 first -> %s" % code)
        return 1
    print("(3a) POST /v1/witness/respond X-JoyKey=w1 -> 204")

    # (3b) w1 再投一次，body 增加 points_event_id=pe_1，预期仍 204（joykey 去重，不刷票）
    body_w1_replay = dict(witness_body)
    body_w1_replay["points_event_id"] = "pe_1"
    code, _ = post_json(
        opener, base, "/v1/witness/respond", body_w1_replay, timeout,
        extra_headers={"X-JoyKey": "w1"},
    )
    if code != 204:
        print("FAIL: (3b) witness w1 replay with pe_1 -> %s" % code)
        return 1
    print("(3b) POST /v1/witness/respond X-JoyKey=w1 points_event_id=pe_1 -> 204")

    # (3c) GET 断言 WITNESS_TALLY summary 含 OCCUPIED=1（没被刷成 2）
    code, out = get_json(opener, base, "/v1/incidents?incident_id=" + incident_id, timeout)
    if code != 200 or not out:
        print("FAIL: (3c) GET /v1/incidents ->", code, out)
        return 1
    incidents = out.get("incidents") or []
    if len(incidents) != 1:
        print("FAIL: (3c) expected exactly one incident", incidents)
        return 1
    inc = incidents[0]
    ai_insights = inc.get("ai_insights") or []
    tally_insight = next((x for x in ai_insights if x.get("insight_type") == "WITNESS_TALLY"), None)
    if not tally_insight:
        print("FAIL: (3c) no WITNESS_TALLY", ai_insights)
        return 1
    summary = tally_insight.get("summary", "")
    if "OCCUPIED=1" not in summary:
        print("FAIL: (3c) 刷票漏洞回归 - summary 应含 OCCUPIED=1, got:", summary)
        return 1
    print("(3c) GET /v1/incidents -> WITNESS_TALLY summary:", summary)

    # 额外检查：evil joykey 不在 allowlist，预期 403
    body_evil = dict(witness_body)
    code, _ = post_json(
        opener, base, "/v1/witness/respond", body_evil, timeout,
        extra_headers={"X-JoyKey": "evil"},
    )
    if code != 403:
        print("FAIL: (3x) witness evil should be 403, got", code)
        return 1
    print("(3x) POST /v1/witness/respond X-JoyKey=evil -> 403 (not allowed)")

    # (3d) w2 投一次（不带 points_event_id），再 GET 校验 EVIDENCE_CONFIRMED + OCCUPIED=2
    code, _ = post_json(
        opener, base, "/v1/witness/respond", witness_body, timeout,
        extra_headers={"X-JoyKey": "w2"},
    )
    if code != 204:
        print("FAIL: (3d) witness w2 -> %s" % code)
        return 1
    print("(3d) POST /v1/witness/respond X-JoyKey=w2 -> 204")
    code, out = get_json(opener, base, "/v1/incidents?incident_id=" + incident_id, timeout)
    if code != 200 or not out:
        print("FAIL: (3d) GET /v1/incidents ->", code, out)
        return 1
    inc = (out.get("incidents") or [{}])[0]
    status = inc.get("incident_status")
    if status != "EVIDENCE_CONFIRMED":
        print("FAIL: (3d) incident_status expected EVIDENCE_CONFIRMED, got", status)
        return 1
    tally_insight = next((x for x in (inc.get("ai_insights") or []) if x.get("insight_type") == "WITNESS_TALLY"), None)
    summary = (tally_insight or {}).get("summary", "")
    if "OCCUPIED=2" not in summary:
        print("FAIL: (3d) expected OCCUPIED=2 in summary, got:", summary)
        return 1
    print("(3d) GET /v1/incidents -> incident_status=", status, "| WITNESS_TALLY summary:", summary)

    # 5) 重复投票：w2 再投一次 -> 仍 204，tally 不变（summary 里 OCCUPIED=2 不变）
    code, _ = post_json(
        opener, base, "/v1/witness/respond", witness_body, timeout,
        extra_headers={"X-JoyKey": "w2"},
    )
    if code != 204:
        print("FAIL: duplicate witness (w2 again) ->", code)
        return 1
    print("(5) POST /v1/witness/respond (duplicate w2) -> 204")
    code, out = get_json(opener, base, "/v1/incidents?incident_id=" + incident_id, timeout)
    if code != 200 or not out:
        print("FAIL: GET /v1/incidents after duplicate ->", code, out)
        return 1
    inc2 = (out.get("incidents") or [{}])[0]
    tally2 = next((x for x in (inc2.get("ai_insights") or []) if x.get("insight_type") == "WITNESS_TALLY"), None)
    summary2 = (tally2 or {}).get("summary", "")
    if "OCCUPIED=2" not in summary2:
        print("FAIL: idempotent check - tally should still show OCCUPIED=2, got summary:", summary2)
        return 1
    print("(5b) GET /v1/incidents -> tally unchanged:", summary2)

    print("\nPASS: M8 witness respond (incident_id=%s, EVIDENCE_CONFIRMED, WITNESS_TALLY, idempotent)" % incident_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())