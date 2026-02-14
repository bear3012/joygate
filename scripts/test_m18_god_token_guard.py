#!/usr/bin/env python3
"""
M18 God Token 门禁验收：JOYGATE_UI_GOD_TOKEN 非空时，
1) 不带 X-JoyGate-God 的 POST /v1/incidents/report_blocked -> 403，detail 含 "god token"
2) 带错误 token 的同请求 -> 403
3) 带正确 token 的同请求 -> 2xx
使用 requests.Session()，先 GET /bootstrap；POST 仅对 429/503 重试（0.3/0.6/1.2s）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("FAIL: need requests (pip install requests)", file=sys.stderr)
    sys.exit(1)

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
REPORT_BLOCKED_BODY = {"charger_id": "charger-001", "incident_type": "BLOCKED"}
TRUNCATE = 200
RETRY_SLEEPS = (0.3, 0.6, 1.2)


def _trunc(s: str) -> str:
    if not s:
        return ""
    return s[:TRUNCATE] + ("..." if len(s) > TRUNCATE else "")


def _detail_contains_god_token(text: str) -> bool:
    try:
        d = json.loads(text) if text else {}
        detail = (d.get("detail") or "") if isinstance(d, dict) else ""
        return "god token" in (detail if isinstance(detail, str) else str(detail)).lower()
    except Exception:
        return "god token" in (text or "").lower()


def _post_report_blocked(
    session: requests.Session,
    base_url: str,
    timeout_sec: float,
    god_header: str | None,
) -> tuple[int, str]:
    url = f"{base_url.rstrip('/')}/v1/incidents/report_blocked"
    headers = {"Content-Type": "application/json"}
    if god_header is not None:
        headers["X-JoyGate-God"] = god_header
    last_code, last_text = 0, ""
    for attempt in range(3):
        try:
            r = session.post(url, json=REPORT_BLOCKED_BODY, headers=headers, timeout=timeout_sec)
            code, text = r.status_code, r.text or ""
            if code in (429, 503) and attempt < 2:
                time.sleep(RETRY_SLEEPS[attempt])
                continue
            return code, text
        except Exception as e:
            last_code, last_text = -1, str(e)
            if attempt < 2:
                time.sleep(RETRY_SLEEPS[attempt])
    return last_code, last_text


def main() -> int:
    p = argparse.ArgumentParser(description="M18 God Token guard: 403 without/wrong token, 2xx with correct")
    p.add_argument("--base_url", default=BASE_URL_DEFAULT, help="Base URL")
    p.add_argument("--token", default=None, help="God token (default: JOYGATE_UI_GOD_TOKEN env)")
    p.add_argument("--timeout_sec", type=float, default=8.0, help="Request timeout seconds")
    args = p.parse_args()

    token = (args.token or os.environ.get("JOYGATE_UI_GOD_TOKEN") or "").strip()
    if not token:
        print("FAIL: token required (--token or JOYGATE_UI_GOD_TOKEN); exit 2", file=sys.stderr)
        sys.exit(2)

    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec
    session = requests.Session()

    # Bootstrap
    try:
        r = session.get(f"{base}/bootstrap", timeout=timeout)
    except Exception as e:
        print(f"FAIL: bootstrap request error {e}")
        sys.exit(1)
    if r.status_code != 200:
        print(f"FAIL: bootstrap status={r.status_code} body={_trunc(r.text)}")
        sys.exit(1)
    print(f"OK: bootstrap {r.status_code} {_trunc(r.text)}")

    fails = 0

    # 1) No X-JoyGate-God -> 403, detail contains "god token"
    code, text = _post_report_blocked(session, base, timeout, god_header=None)
    if code != 403 or not _detail_contains_god_token(text):
        print(f"FAIL: no header -> expect 403 + detail 'god token', got {code} {_trunc(text)}")
        fails += 1
    else:
        print(f"OK: no header -> {code} {_trunc(text)}")

    # 2) Wrong token -> 403
    code, text = _post_report_blocked(session, base, timeout, god_header="wrong_token_xyz")
    if code != 403 or not _detail_contains_god_token(text):
        print(f"FAIL: wrong token -> expect 403 + detail 'god token', got {code} {_trunc(text)}")
        fails += 1
    else:
        print(f"OK: wrong token -> {code} {_trunc(text)}")

    # 3) Correct token -> 2xx
    code, text = _post_report_blocked(session, base, timeout, god_header=token)
    if code not in (200, 202, 204):
        print(f"FAIL: correct token -> expect 2xx, got {code} {_trunc(text)}")
        fails += 1
    else:
        print(f"OK: correct token -> {code} {_trunc(text)}")

    if fails:
        sys.exit(1)
    print("PASS: all M18 god token guard checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
