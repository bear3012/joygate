#!/usr/bin/env python3
"""Sandbox header 签名校验：无 ts/sig 或 sig 错或 ts 过期 -> 400；正确 header -> 200；cookie 优先不覆盖。"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import time

import requests

import joygate.config  # ensure .env loaded


def _expected_sig(secret: str, ts: int, sandbox_id: str) -> str:
    msg = f"{ts}.{sandbox_id}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandbox header signature guard: 400 on invalid, 200 on valid; cookie wins")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--secret", default=os.getenv("JOYGATE_SANDBOX_HEADER_SECRET", "").strip(), help="default: env JOYGATE_SANDBOX_HEADER_SECRET")
    parser.add_argument("--ttl", type=int, default=300, help="TTL seconds for expiry test")
    parser.add_argument("--timeout", type=float, default=10.0, help="request timeout seconds")
    args = parser.parse_args()
    if not args.secret:
        print("FAIL: --secret or JOYGATE_SANDBOX_HEADER_SECRET required", file=sys.stderr)
        return 1
    base = args.base_url.rstrip("/")
    url = f"{base}/bootstrap"
    session = requests.Session()
    sandbox_a = "aaaaaaaaaaaaaaaa"
    sandbox_b = "bbbbbbbbbbbbbbbb"
    sandbox_c = "cccccccccccccccc"
    sandbox_d = "dddddddddddddddd"
    sandbox_e = "eeeeeeeeeeeeeeee"

    # Case A: only X-JoyGate-Sandbox, no ts/sig -> 400, body contains invalid sandbox header
    r = session.get(url, headers={"X-JoyGate-Sandbox": sandbox_a}, timeout=args.timeout)
    if r.status_code != 400:
        print(f"FAIL: Case A expected 400, got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    if "invalid sandbox header" not in (r.text or ""):
        print(f"FAIL: Case A body must contain 'invalid sandbox header', got {r.text}", file=sys.stderr)
        return 1
    print("OK: Case A (no ts/sig) -> 400 invalid sandbox header")

    # Case B: ts present but wrong sig (format correct, value wrong) -> 400
    wrong_sig = "sha256=" + ("0" * 64)
    ts_b = int(time.time())
    r = session.get(
        url,
        headers={
            "X-JoyGate-Sandbox": sandbox_b,
            "X-JoyGate-Sandbox-Timestamp": str(ts_b),
            "X-JoyGate-Sandbox-Signature": wrong_sig,
        },
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: Case B expected 400, got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    if "invalid sandbox header" not in (r.text or ""):
        print(f"FAIL: Case B body must contain 'invalid sandbox header', got {r.text}", file=sys.stderr)
        return 1
    print("OK: Case B (wrong sig) -> 400 invalid sandbox header")

    # Case C: correct sig but ts expired (now - (ttl + 10)) -> 400
    ts_c = int(time.time()) - (args.ttl + 10)
    sig_c = _expected_sig(args.secret, ts_c, sandbox_c)
    r = session.get(
        url,
        headers={
            "X-JoyGate-Sandbox": sandbox_c,
            "X-JoyGate-Sandbox-Timestamp": str(ts_c),
            "X-JoyGate-Sandbox-Signature": sig_c,
        },
        timeout=args.timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: Case C expected 400 (expired ts), got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    if "invalid sandbox header" not in (r.text or ""):
        print(f"FAIL: Case C body must contain 'invalid sandbox header', got {r.text}", file=sys.stderr)
        return 1
    print("OK: Case C (expired ts) -> 400 invalid sandbox header")

    # Case D: correct sig and ts in window -> 200, cookie joygate_sandbox == header sandbox_id
    ts_d = int(time.time())
    sig_d = _expected_sig(args.secret, ts_d, sandbox_d)
    # clear cookie so we rely on header only
    session.cookies.clear()
    r = session.get(
        url,
        headers={
            "X-JoyGate-Sandbox": sandbox_d,
            "X-JoyGate-Sandbox-Timestamp": str(ts_d),
            "X-JoyGate-Sandbox-Signature": sig_d,
        },
        timeout=args.timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: Case D expected 200, got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    cookie_val = session.cookies.get("joygate_sandbox")
    if cookie_val != sandbox_d:
        print(f"FAIL: Case D cookie joygate_sandbox should be {sandbox_d!r}, got {cookie_val!r}", file=sys.stderr)
        return 1
    print("OK: Case D (valid header) -> 200, cookie set")

    # Case E: cookie already exists; send another sandbox header (valid sig) -> 200, cookie unchanged (cookie 优先)
    ts_e = int(time.time())
    sig_e = _expected_sig(args.secret, ts_e, sandbox_e)
    r = session.get(
        url,
        headers={
            "X-JoyGate-Sandbox": sandbox_e,
            "X-JoyGate-Sandbox-Timestamp": str(ts_e),
            "X-JoyGate-Sandbox-Signature": sig_e,
        },
        timeout=args.timeout,
    )
    if r.status_code != 200:
        print(f"FAIL: Case E expected 200, got {r.status_code} body={r.text}", file=sys.stderr)
        return 1
    cookie_after = session.cookies.get("joygate_sandbox")
    if cookie_after != sandbox_d:
        print(f"FAIL: Case E cookie should remain {sandbox_d!r} (cookie 优先), got {cookie_after!r}", file=sys.stderr)
        return 1
    print("OK: Case E (cookie 优先, header 不覆盖) -> 200, cookie unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
