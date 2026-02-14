#!/usr/bin/env python3
"""
M9.4 Outbound Webhooks 最小闭环验收：
- 本地 webhook 接收 server
- 创建订阅
- 触发 INCIDENT_CREATED / INCIDENT_STATUS_CHANGED / AI_JOB_STATUS_CHANGED
- 校验签名与 payload
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import sys

_scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts_dir))
from _sandbox_client import get_bootstrapped_session  # noqa: E402


class _WebhookCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []

    def add(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)


def _make_handler(collector: _WebhookCollector):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            collector.add(
                {
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                }
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return

    return Handler


def _verify_signature(secret: str, ts: str, body: bytes, sig: str) -> bool:
    msg = ts.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), msg=msg, digestmod=hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest((sig or "").strip(), expected)


def main() -> int:
    p = argparse.ArgumentParser(description="M9.4 outbound webhooks test")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()

    collector = _WebhookCollector()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(collector))
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    secret = "test_secret"
    target_url = f"http://{host}:{port}/hook"

    try:
        session = get_bootstrapped_session(args.base_url, args.timeout)
        r = session.post(
            f"{args.base_url}/v1/webhooks/subscriptions",
            json={
                "target_url": target_url,
                "event_types": [
                    "INCIDENT_CREATED",
                    "INCIDENT_STATUS_CHANGED",
                    "AI_JOB_STATUS_CHANGED",
                ],
                "secret": secret,
                "is_enabled": True,
            },
            timeout=args.timeout,
        )
        if r.status_code != 200:
            print(f"FAIL: create subscription -> {r.status_code} {r.text}")
            return 1
        sub = r.json()
        if "secret" in sub:
            print("FAIL: subscription response must not include secret")
            return 1

        r = session.post(
            f"{args.base_url}/v1/incidents/report_blocked",
            json={"charger_id": "charger-001", "incident_type": "BLOCKED"},
            timeout=args.timeout,
        )
        if r.status_code != 200:
            print(f"FAIL: report_blocked -> {r.status_code} {r.text}")
            return 1
        incident_id = r.json().get("incident_id")
        if not incident_id:
            print("FAIL: missing incident_id")
            return 1

        r = session.post(
            f"{args.base_url}/v1/incidents/update_status",
            json={"incident_id": incident_id, "incident_status": "ESCALATED"},
            timeout=args.timeout,
        )
        if r.status_code != 204:
            print(f"FAIL: update_status -> {r.status_code} {r.text}")
            return 1

        r = session.post(
            f"{args.base_url}/v1/ai_jobs/vision_audit",
            json={"incident_id": incident_id},
            timeout=args.timeout,
        )
        if r.status_code != 200:
            print(f"FAIL: create job -> {r.status_code} {r.text}")
            return 1

        r = session.post(
            f"{args.base_url}/v1/ai_jobs/tick",
            json={"max_jobs": 1},
            timeout=args.timeout,
        )
        if r.status_code != 200:
            print(f"FAIL: tick -> {r.status_code} {r.text}")
            return 1

        deadline = time.time() + max(3.0, args.timeout * 2)
        while time.time() < deadline:
            if len(collector.items()) >= 3:
                break
            time.sleep(0.05)

        items = collector.items()
        if len(items) < 3:
            print(f"FAIL: expected >=3 webhook calls, got {len(items)}")
            return 1

        seen_types: set[str] = set()
        for item in items:
            headers = item.get("headers") or {}
            body = item.get("body") or b""
            ts = headers.get("x-joygate-timestamp")
            sig = headers.get("x-joygate-signature")
            if not ts or not sig:
                print("FAIL: missing signature headers")
                return 1
            if not _verify_signature(secret, ts, body, sig):
                print("FAIL: signature mismatch")
                return 1
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                print("FAIL: invalid JSON body")
                return 1
            for key in ("event_id", "event_type", "occurred_at", "object_type", "object_id", "data"):
                if key not in payload:
                    print(f"FAIL: missing payload key {key}")
                    return 1
            event_type = payload.get("event_type")
            seen_types.add(event_type)
            data = payload.get("data") or {}
            if event_type in ("INCIDENT_CREATED", "INCIDENT_STATUS_CHANGED"):
                expected_keys = {
                    "incident_id",
                    "incident_type",
                    "incident_status",
                    "charger_id",
                    "segment_id",
                    "snapshot_ref",
                    "evidence_refs",
                    "ai_insights",
                }
                if set(data.keys()) != expected_keys:
                    print(f"FAIL: incident data keys mismatch: {set(data.keys())}")
                    return 1
            if event_type == "AI_JOB_STATUS_CHANGED":
                for k in ("ai_job_id", "ai_job_type", "ai_job_status", "incident_id"):
                    if k not in data:
                        print(f"FAIL: ai_job data missing {k}")
                        return 1

        if not {
            "INCIDENT_CREATED",
            "INCIDENT_STATUS_CHANGED",
            "AI_JOB_STATUS_CHANGED",
        }.issubset(seen_types):
            print(f"FAIL: missing event types: {seen_types}")
            return 1

        print("OK: outbound webhooks M9.4 passed.")
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
