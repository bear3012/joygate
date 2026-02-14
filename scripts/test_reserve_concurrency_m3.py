#!/usr/bin/env python3
"""
M3 并发一致性：多线程并发 reserve 同一 charger，只允许 1 个成功。
仅用标准库（urllib + threading）。
"""
from __future__ import annotations

import argparse
import json
import threading
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE_URL = "http://127.0.0.1:8014"
DEFAULT_N = 20
DEFAULT_TIMEOUT = 5.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M3 reserve concurrency test")
    p.add_argument("--base_url", default=DEFAULT_BASE_URL, help="Base URL")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="Concurrent requests")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout seconds")
    return p.parse_args()


def _get_cookie(base_url: str, timeout: float) -> str | None:
    url = base_url.rstrip("/") + "/bootstrap"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            set_cookie = resp.headers.get("Set-Cookie", "")
            for part in set_cookie.split(";"):
                part = part.strip()
                if part.startswith("joygate_sandbox="):
                    return part.split("=", 1)[1]
    except (HTTPError, URLError, OSError, TimeoutError):
        return None
    return None


def _post_reserve(base_url: str, cookie: str, joykey: str, timeout: float) -> tuple[int, str | None]:
    url = base_url.rstrip("/") + "/v1/reserve"
    body = {
        "resource_type": "CHARGER",
        "resource_id": "charger-001",
        "joykey": joykey,
        "action": "HOLD",
    }
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", f"joygate_sandbox={cookie}")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), raw
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, raw
    except (URLError, OSError, TimeoutError) as e:
        return 0, str(e)


def _get_snapshot(base_url: str, cookie: str, timeout: float) -> tuple[int, dict[str, Any] | None]:
    url = base_url.rstrip("/") + "/v1/snapshot"
    req = Request(url, method="GET")
    if cookie:
        req.add_header("Cookie", f"joygate_sandbox={cookie}")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else None
    except (URLError, OSError, TimeoutError):
        return 0, None


def main() -> int:
    args = parse_args()
    base_url = args.base_url
    n = max(1, args.n)
    timeout = args.timeout

    cookie = _get_cookie(base_url, timeout)
    if not cookie:
        print("FAIL: bootstrap did not return joygate_sandbox cookie")
        return 1

    results: list[tuple[int, str | None]] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        joykey = f"jk_conc_{i:03d}"
        try:
            barrier.wait(timeout=timeout)
        except threading.BrokenBarrierError:
            pass
        code, body = _post_reserve(base_url, cookie, joykey, timeout)
        with lock:
            results.append((code, body))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 1)

    counts: dict[int, int] = {}
    for code, _ in results:
        counts[code] = counts.get(code, 0) + 1

    ok_200 = counts.get(200, 0)
    busy_409 = counts.get(409, 0)
    other = {k: v for k, v in counts.items() if k not in (200, 409)}

    print(f"reserve_concurrency: total={len(results)} 200={ok_200} 409={busy_409} other={other}")

    snap_code, snap = _get_snapshot(base_url, cookie, timeout)
    if snap_code != 200 or not isinstance(snap, dict):
        print(f"FAIL: snapshot invalid: code={snap_code}, body={snap}")
        return 1

    chargers = snap.get("chargers") or []
    holds = snap.get("holds") or []
    target = [c for c in chargers if c.get("charger_id") == "charger-001"]
    if not target or target[0].get("slot_state") != "HELD":
        print("FAIL: charger-001 not HELD in snapshot")
        return 1
    if len([h for h in holds if h.get("charger_id") == "charger-001"]) != 1:
        print("FAIL: holds for charger-001 != 1")
        return 1

    if ok_200 != 1 or (ok_200 + busy_409) != len(results) or other:
        print("FAIL: unexpected status distribution")
        return 1

    print("OK: reserve concurrency M3 passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
