#!/usr/bin/env python3
"""
并发压测 GET /v1/incidents：使用 requests + json。
支持正常请求与按比例非法枚举请求（incident_type=GARBAGE / incident_status=GARBAGE），
校验 200 含 incidents 列表、400 含 detail+GARBAGE，其它/异常分别统计。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from _sandbox_client import get_bootstrapped_session

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_N = 100
DEFAULT_CONCURRENCY = 50
DEFAULT_TIMEOUT_SEC = 3
DEFAULT_INVALID_RATE = 0.1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Concurrent load test for GET /v1/incidents")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL (default: %(default)s)")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="Total requests (default: %(default)s)")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrency (default: %(default)s)")
    p.add_argument("--timeout_sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="Request timeout seconds (default: %(default)s)")
    p.add_argument("--invalid_rate", type=float, default=DEFAULT_INVALID_RATE, help="Fraction of invalid-enum requests 0..1 (default: %(default)s)")
    return p.parse_args()


def do_one(
    base_url: str,
    timeout_sec: float,
    use_invalid: bool,
    invalid_type: str,
    cookie_val: str,
    cookie_domain: str,
) -> tuple[str, int, str | None, str | None]:
    """
    发一次请求。返回 (result_kind, status_code, body_snippet, error_msg).
    result_kind: "200_ok" | "400_ok" | "invalid_body" | "unexpected_status" | "exception"
    """
    url = base_url.rstrip("/") + "/v1/incidents"
    if use_invalid:
        if invalid_type == "type":
            url += "?incident_type=GARBAGE"
        else:
            url += "?incident_status=GARBAGE"

    session = requests.Session()
    cookie = requests.cookies.create_cookie(
        name="joygate_sandbox",
        value=cookie_val,
        domain=cookie_domain,
        path="/",
    )
    session.cookies.set_cookie(cookie)
    try:
        resp = session.get(url, timeout=timeout_sec)
        status = resp.status_code
        raw = resp.text
    except requests.RequestException as e:
        return ("exception", 0, None, str(e))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ("invalid_body", status, raw[:200] if raw else None, "not valid JSON")

    if status == 200:
        if isinstance(data.get("incidents"), list):
            return ("200_ok", status, None, None)
        return ("invalid_body", status, raw[:200], "incidents missing or not a list")
    if status == 400:
        detail = data.get("detail") if isinstance(data.get("detail"), str) else ""
        if "GARBAGE" in detail:
            return ("400_ok", status, None, None)
        return ("invalid_body", status, raw[:200], "detail missing or no GARBAGE")
    return ("unexpected_status", status, raw[:200], None)


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    n = args.n
    concurrency = args.concurrency
    timeout_sec = args.timeout_sec
    invalid_rate = max(0.0, min(1.0, args.invalid_rate))

    # 先 bootstrap 获取 cookie（并发 worker 共享同一 sandbox）
    session = get_bootstrapped_session(base_url, timeout_sec)
    cookie_val = session.cookies.get("joygate_sandbox")
    if not cookie_val:
        print("bootstrap: fail (missing joygate_sandbox cookie)")
        return 1
    parsed = urlparse(base_url)
    cookie_domain = parsed.hostname or "127.0.0.1"

    # 预生成任务：每个任务 (use_invalid, invalid_type)
    rng = random.Random()
    tasks = []
    for _ in range(n):
        use_invalid = rng.random() < invalid_rate
        invalid_type = "type" if rng.random() < 0.5 else "status"
        tasks.append((use_invalid, invalid_type))

    counts = {
        "200_ok": 0,
        "400_ok": 0,
        "invalid_body": 0,
        "unexpected_status": 0,
        "exception": 0,
    }
    samples = []  # list of (kind, status, snippet, err)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                do_one, base_url, timeout_sec, use_inv, inv_type, cookie_val, cookie_domain
            ): (use_inv, inv_type)
            for use_inv, inv_type in tasks
        }
        for fut in as_completed(futures):
            kind, status, snippet, err = fut.result()
            counts[kind] += 1
            if kind in ("invalid_body", "unexpected_status", "exception") and len(samples) < 3:
                samples.append((kind, status, snippet, err))
    elapsed = time.perf_counter() - t0

    print(f"elapsed_sec={elapsed:.3f}")
    print(f"200_ok={counts['200_ok']} 400_ok={counts['400_ok']} invalid_body={counts['invalid_body']} unexpected_status={counts['unexpected_status']} exception={counts['exception']}")
    for i, (kind, status, snippet, err) in enumerate(samples):
        print(f"sample[{i}] {kind} status={status} err={err!r} snippet={repr(snippet)[:80] if snippet else None}")

    if counts["invalid_body"] > 0 or counts["unexpected_status"] > 0 or counts["exception"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
