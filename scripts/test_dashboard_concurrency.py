#!/usr/bin/env python3
"""
并发稳定性测试：多线程同时写 /v1/incidents/report_blocked 与读 /dashboard/incidents_daily，
验证 dashboard 在高并发下不会 500/timeout，且页面仍包含 data-testid=\"summary-total\" 锚点。

仅使用 Python 标准库：threading / time / urllib.request。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8025"
DEFAULT_SECONDS = 10
DEFAULT_WRITERS = 5
DEFAULT_READERS = 5
DEFAULT_TIMEOUT_SEC = 2.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Concurrent smoke test: incidents write + dashboard read (HTML with data-testid anchors)."
    )
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL (default: %(default)s)")
    p.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="Test duration in seconds")
    p.add_argument("--writers", type=int, default=DEFAULT_WRITERS, help="Number of writer threads")
    p.add_argument("--readers", type=int, default=DEFAULT_READERS, help="Number of reader threads")
    p.add_argument("--timeout_sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="Per-request timeout seconds")
    return p.parse_args()


def _post_json(base_url: str, path: str, body: dict[str, Any], timeout: float) -> tuple[int, str | None, str | None]:
    """
    简化版 POST：返回 (status_code, raw_body_or_none, err_or_none)。
    解析 JSON 与否对本测试不关键，仅关注 status / 错误。
    """
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), raw or None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, raw or None, None
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def _get_text(base_url: str, path: str, timeout: float) -> tuple[int, str | None, str | None]:
    """GET 纯文本：返回 (status_code, raw_body_or_none, err_or_none)。"""
    url = base_url.rstrip("/") + path
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), raw or None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, raw or None, None
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def main() -> int:
    args = parse_args()
    base_url: str = args.base_url
    seconds: float = args.seconds
    writers: int = args.writers
    readers: int = args.readers
    timeout_sec: float = args.timeout_sec

    end_at = time.time() + seconds

    lock = threading.Lock()
    post_total = post_200 = post_other = post_err = 0
    get_total = get_200 = get_other = get_err = 0
    first_bad_get: dict[str, Any] | None = None

    def writer_worker() -> None:
        nonlocal post_total, post_200, post_other, post_err
        body = {"charger_id": "charger-001", "incident_type": "BLOCKED"}
        while time.time() < end_at:
            status, raw, err = _post_json(base_url, "/v1/incidents/report_blocked", body, timeout_sec)
            with lock:
                post_total += 1
                if err is not None or status == 0:
                    post_err += 1
                elif status == 200:
                    post_200 += 1
                else:
                    post_other += 1

    def reader_worker() -> None:
        nonlocal get_total, get_200, get_other, get_err, first_bad_get
        while time.time() < end_at:
            status, raw, err = _get_text(base_url, "/dashboard/incidents_daily", timeout_sec)
            with lock:
                get_total += 1
                if err is not None or status == 0:
                    get_err += 1
                    if first_bad_get is None:
                        first_bad_get = {
                            "status": status,
                            "err": err,
                            "raw": (raw[:200] + "..." if raw and len(raw) > 200 else raw),
                        }
                elif status == 200:
                    # 简单 HTML 健康检查：必须包含 data-testid=\"summary-total\"
                    get_200 += 1
                    if raw is not None and "data-testid=\"summary-total\"" not in raw:
                        get_other += 1
                        if first_bad_get is None:
                            first_bad_get = {
                                "status": status,
                                "err": "missing summary-total testid",
                                "raw": (raw[:200] + "..." if len(raw) > 200 else raw),
                            }
                else:
                    get_other += 1
                    if first_bad_get is None:
                        first_bad_get = {
                            "status": status,
                            "err": err,
                            "raw": (raw[:200] + "..." if raw and len(raw) > 200 else raw),
                        }

    threads: list[threading.Thread] = []
    for _ in range(writers):
        t = threading.Thread(target=writer_worker, daemon=True)
        threads.append(t)
        t.start()
    for _ in range(readers):
        t = threading.Thread(target=reader_worker, daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 汇总输出
    print(f"seconds={seconds}")
    print(f"post: total={post_total}, 200={post_200}, other={post_other}, err={post_err}")
    print(f"get:  total={get_total}, 200={get_200}, other={get_other}, err={get_err}")
    if first_bad_get is not None:
        print("first_bad_get:", json.dumps(first_bad_get, ensure_ascii=False))
    else:
        print("first_bad_get: None")

    # 退出码规则
    if get_other > 0 or get_err > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

