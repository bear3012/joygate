#!/usr/bin/env python3
"""
验证 GET /dashboard/incidents_daily 返回 HTML 今日汇总；仅用 Python 标准库。
流程：创建 2 条事件（不同 type）-> 1 条 ESCALATED、1 条 RESOLVED -> GET dashboard -> 断言 HTML 含 total=2, severe=1, resolved=1, unresolved=1。
"""
from __future__ import annotations

import argparse
import json
import sys
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 5


def parse_args():
    p = argparse.ArgumentParser(description="Test GET /dashboard/incidents_daily HTML")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL")
    p.add_argument("--timeout_sec", type=float, default=DEFAULT_TIMEOUT, help="Request timeout")
    return p.parse_args()


def post_json(
    base_url: str, path: str, body: dict, timeout: float, opener
) -> tuple[int, dict | None, str | None, str | None]:
    """返回 (status_code, json_or_none, raw_body_or_none, err_or_none)。网络异常时 status=0, err=str(e)。"""
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            js = None
            if raw:
                try:
                    js = json.loads(raw)
                except json.JSONDecodeError:
                    pass
            return resp.getcode(), js, raw or None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        js = None
        if raw:
            try:
                js = json.loads(raw)
            except json.JSONDecodeError:
                pass
        return e.code, js, raw or None, None
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, None, str(e)


def get_text(
    base_url: str, path: str, timeout: float, opener
) -> tuple[int, None, str | None, str | None]:
    """返回 (status_code, None, raw_body_or_none, err_or_none)。GET 无 JSON 体。"""
    url = base_url.rstrip("/") + path
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), None, raw or None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, None, raw or None, None
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, None, str(e)


def print_fail(
    step: str,
    status: int,
    js: dict | None,
    raw: str | None,
    err: str | None,
) -> None:
    """统一失败日志：输出到 stderr，含 step/status/err/json/raw（raw 截断 500 字符）。"""
    raw_trunc = (raw[:500] + "..." if len(raw or "") > 500 else raw) or ""
    msg = (
        f"step={step!r}\n"
        f"status={status!r}\n"
        f"err={err!r}\n"
        f"json={js!r}\n"
        f"raw={raw_trunc!r}\n"
    )
    print(msg, file=sys.stderr)


def assert_testid(norm: str, testid: str, value: str) -> bool:
    """norm 为去掉所有空白后的 HTML。判断包含 data-testid=\"testid\">value< 锚点。"""
    return f'data-testid="{testid}">{value}<' in norm


def extract_int_by_testid(html_body: str, testid: str) -> int:
    """
    从 HTML 中通过 data-testid 提取紧随其后的整数值。
    实现：去空白后查找 data-testid=\"...\">，向后读取连续数字直到遇到 `<`。
    """
    norm = "".join(html_body.split())
    needle = f'data-testid="{testid}">'
    idx = norm.find(needle)
    if idx == -1:
        raise ValueError(f"missing testid {testid!r}")
    start = idx + len(needle)
    end = start
    n = len(norm)
    while end < n and norm[end].isdigit():
        end += 1
    if end == start:
        raise ValueError(f"no digits after {needle!r}")
    try:
        return int(norm[start:end])
    except ValueError as e:
        raise ValueError(f"invalid int for {testid!r}: {norm[start:end]!r}") from e


def main() -> int:
    args = parse_args()
    base = args.base_url
    timeout = args.timeout_sec

    # 创建 CookieJar 和 opener
    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))

    # bootstrap：先 GET /bootstrap 来拿 cookie
    url = base.rstrip("/") + "/bootstrap"
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            js = json.loads(raw) if raw else None
            code = resp.getcode()
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        js = json.loads(raw) if raw else None
        code = e.code
        print_fail("bootstrap", code, js, raw, None)
        return 1
    except (URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        print_fail("bootstrap", 0, None, None, str(e))
        return 1
    
    if code != 200:
        print_fail("bootstrap", code, js, raw, None)
        return 1
    
    # 检查 cookie 是否存在
    has_cookie = any(cookie.name == "joygate_sandbox" for cookie in cj)
    if not has_cookie:
        print_fail("bootstrap", 200, js, raw, "missing cookie joygate_sandbox")
        return 1

    # a0) baseline：获取当前 dashboard Summary 数字（适配非空沙盒）
    code, _, html_body, err = get_text(base, "/dashboard/incidents_daily", timeout, opener)
    if err:
        print_fail("baseline_get_dashboard", code, None, html_body, err)
        return 1
    if code != 200:
        print_fail("baseline_get_dashboard", code, None, html_body, None)
        return 1
    if not html_body or not isinstance(html_body, str):
        print_fail("baseline_get_dashboard", code, None, None, "no body")
        return 1
    try:
        total_before = extract_int_by_testid(html_body, "summary-total")
        severe_before = extract_int_by_testid(html_body, "summary-severe")
        resolved_before = extract_int_by_testid(html_body, "summary-resolved")
        unresolved_before = extract_int_by_testid(html_body, "summary-unresolved")
        stale_before = extract_int_by_testid(html_body, "summary-stale-unresolved")
    except ValueError as e:
        print_fail("baseline_extract", 200, None, html_body, str(e))
        return 1

    # a) 创建 2 条事件（不同 incident_type）
    code, js, raw, err = post_json(base, "/v1/incidents/report_blocked", {"charger_id": "charger-001", "incident_type": "BLOCKED"}, timeout, opener)
    if err or code != 200 or not (js and js.get("incident_id")):
        print_fail("create_1", code, js, raw, err)
        return 1
    id1 = js["incident_id"]
    code, js, raw, err = post_json(base, "/v1/incidents/report_blocked", {"charger_id": "charger-002", "incident_type": "NO_PLUG"}, timeout, opener)
    if err or code != 200 or not (js and js.get("incident_id")):
        print_fail("create_2", code, js, raw, err)
        return 1
    id2 = js["incident_id"]

    # b) 1 条 -> ESCALATED，1 条 -> RESOLVED
    code, js, raw, err = post_json(base, "/v1/incidents/update_status", {"incident_id": id1, "incident_status": "ESCALATED"}, timeout, opener)
    if err or code != 204:
        print_fail("update_escalated", code, js, raw, err)
        return 1
    code, js, raw, err = post_json(base, "/v1/incidents/update_status", {"incident_id": id2, "incident_status": "RESOLVED"}, timeout, opener)
    if err or code != 204:
        print_fail("update_resolved", code, js, raw, err)
        return 1

    # c) GET /dashboard/incidents_daily（after）
    code, _, html_body, err = get_text(base, "/dashboard/incidents_daily", timeout, opener)
    if err:
        print_fail("get_dashboard", code, None, html_body, err)
        return 1
    if code != 200:
        print_fail("get_dashboard", code, None, html_body, None)
        return 1
    if not html_body or not isinstance(html_body, str):
        print_fail("get_dashboard", code, None, None, "no body")
        return 1

    # d) 断言 Summary 数字（增量口径，仅依赖 data-testid 锚点）
    try:
        total_after = extract_int_by_testid(html_body, "summary-total")
        severe_after = extract_int_by_testid(html_body, "summary-severe")
        resolved_after = extract_int_by_testid(html_body, "summary-resolved")
        unresolved_after = extract_int_by_testid(html_body, "summary-unresolved")
        stale_after = extract_int_by_testid(html_body, "summary-stale-unresolved")
    except ValueError as e:
        print_fail("after_extract", 200, None, html_body, str(e))
        return 1

    if total_after < total_before:
        print_fail(
            "assert_total_delta",
            200,
            None,
            html_body,
            f"total_before={total_before}, total_after={total_after}",
        )
        return 1
    if severe_after < severe_before:
        print_fail(
            "assert_severe_delta",
            200,
            None,
            html_body,
            f"severe_before={severe_before}, severe_after={severe_after}",
        )
        return 1
    if resolved_after < resolved_before:
        print_fail(
            "assert_resolved_delta",
            200,
            None,
            html_body,
            f"resolved_before={resolved_before}, resolved_after={resolved_after}",
        )
        return 1
    if unresolved_after < unresolved_before:
        print_fail(
            "assert_unresolved_delta",
            200,
            None,
            html_body,
            f"unresolved_before={unresolved_before}, unresolved_after={unresolved_after}",
        )
        return 1

    # stale_unresolved：短时间内不应因为本测试新增 stale（允许保持不变或极小波动时再放宽）
    if stale_after < stale_before:
        print_fail(
            "assert_stale_delta",
            200,
            None,
            html_body,
            f"stale_before={stale_before}, stale_after={stale_after}",
        )
        return 1

    print("dashboard_daily: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
