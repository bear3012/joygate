from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import requests

from joygate.webhook_target_url import validate_webhook_target_url


def serialize_webhook_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def build_signature(secret: str | None, ts: str, body: bytes) -> str | None:
    if secret is None or (isinstance(secret, str) and not secret.strip()):
        return None
    key = secret.encode("utf-8")
    msg = ts.encode("utf-8") + b"." + body
    digest = hmac.new(key, msg=msg, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def send_webhook_with_retry(
    target_url: str,
    secret: str | None,
    payload: dict,
    timeout: int,
    max_attempts: int,
    backoff: int,
    allow_http: bool = False,
    allow_localhost: bool = False,
) -> dict:
    """投递前再次校验 target_url；不合法则不发请求，返回 last_error=invalid_target_url。"""
    ok, err = validate_webhook_target_url(target_url, allow_http=allow_http, allow_localhost=allow_localhost)
    if not ok:
        return {
            "delivered": False,
            "attempts": 0,
            "last_status_code": None,
            "last_error": err or "invalid_target_url",
        }

    attempts = int(max_attempts or 0)
    if attempts <= 0:
        attempts = 1
    timeout_sec = int(timeout or 0)
    if timeout_sec <= 0:
        timeout_sec = 10
    backoff_sec = int(backoff or 0)
    if backoff_sec < 0:
        backoff_sec = 0
    last_status_code = None
    last_error: str | None = None
    session = requests.Session()
    session.trust_env = False
    try:
        for attempt in range(1, attempts + 1):
            ok, err = validate_webhook_target_url(target_url, allow_http=allow_http, allow_localhost=allow_localhost)
            if not ok:
                return {
                    "delivered": False,
                    "attempts": attempt - 1,
                    "last_status_code": None,
                    "last_error": "invalid_target_url",
                }
            ts = str(int(time.time()))
            body = serialize_webhook_body(payload)
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "X-JoyGate-Timestamp": ts,
            }
            sig = build_signature(secret, ts, body)
            if sig is not None:
                headers["X-JoyGate-Signature"] = sig
            try:
                resp = session.post(
                    target_url,
                    data=body,
                    headers=headers,
                    timeout=timeout_sec,
                    allow_redirects=False,
                )
                try:
                    if 200 <= resp.status_code < 300:
                        out = {
                            "delivered": True,
                            "attempts": attempt,
                            "last_status_code": resp.status_code,
                            "last_error": None,
                        }
                        return out
                    last_status_code = resp.status_code
                    last_error = "non_2xx_status"
                finally:
                    resp.close()
            except requests.Timeout:
                last_error = "timeout"
                last_status_code = None
            except requests.ConnectionError:
                last_error = "connection_error"
                last_status_code = None
            except requests.RequestException:
                last_error = "connection_error"
                last_status_code = None
            # 不阻塞 worker：不 sleep，重试交给 outbox 下一轮
    finally:
        session.close()

    return {
        "delivered": False,
        "attempts": attempts,
        "last_status_code": last_status_code,
        "last_error": last_error,
    }
