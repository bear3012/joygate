#!/usr/bin/env python3
"""
M9.5 Outbound Webhooks Delivery Ledger 最小闭环验收：
- 本地 webhook 接收 server
- 创建订阅
- 触发三类事件
- 校验 deliveries 列表
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from pathlib import Path
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


def _make_handler(collector: _WebhookCollector, fail_left: list[int]):
    """fail_left[0] = 剩余失败次数；>0 时返回 500 并减 1，否则 200。仍照常 collector.add。"""

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
            if fail_left[0] > 0:
                fail_left[0] -= 1
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"fail")
            else:
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
    p = argparse.ArgumentParser(description="M9.5 outbound webhooks deliveries test")
    p.add_argument("--base_url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--fail_first_n", type=int, default=0, help="handler 前 N 次返回 500，用于验证重试")
    args = p.parse_args()

    collector = _WebhookCollector()
    fail_left = [max(0, args.fail_first_n)]
    server = HTTPServer(("127.0.0.1", 0), _make_handler(collector, fail_left))
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
        subscription_id = sub.get("subscription_id") if isinstance(sub, dict) else None
        if not subscription_id or not str(subscription_id).strip():
            print("FAIL: subscription response missing or empty subscription_id")
            return 1

        r = session.get(f"{args.base_url}/v1/webhooks/deliveries", timeout=args.timeout)
        if r.status_code != 200:
            print(f"FAIL: get deliveries baseline -> {r.status_code} {r.text}")
            return 1
        all_baseline = r.json().get("deliveries") or []
        baseline_delivery_ids = {d.get("delivery_id") for d in all_baseline if d.get("subscription_id") == subscription_id and d.get("delivery_id")}

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

        min_calls = 5 if args.fail_first_n > 0 else 3
        deadline = time.time() + (14.0 if args.fail_first_n > 0 else max(3.0, args.timeout * 2))
        while time.time() < deadline:
            if len(collector.items()) >= min_calls:
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
            event_type = payload.get("event_type")
            seen_types.add(event_type)

        # 异步投递：轮询 GET deliveries，只统计本 subscription 且不在 baseline 的新增，直到新增 >=3 或超时（失败重试时延长至 12 秒）
        deliveries = []
        poll_duration = 12.0 if args.fail_first_n > 0 else 5.0
        poll_deadline = time.time() + poll_duration
        poll_interval = 0.3
        while time.time() < poll_deadline:
            r = session.get(f"{args.base_url}/v1/webhooks/deliveries", timeout=args.timeout)
            if r.status_code != 200:
                print(f"FAIL: get deliveries -> {r.status_code} {r.text}")
                return 1
            all_d = r.json().get("deliveries") or []
            ours = [d for d in all_d if d.get("subscription_id") == subscription_id]
            new_ones = [d for d in ours if d.get("delivery_id") not in baseline_delivery_ids]
            if len(new_ones) >= 3:
                deliveries = ours
                break
            time.sleep(poll_interval)
        if len(deliveries) < 3 or len([d for d in deliveries if d.get("delivery_id") not in baseline_delivery_ids]) < 3:
            print(f"FAIL: expected >=3 new deliveries for this subscription after {poll_duration}s poll, got {len(deliveries)}")
            return 1
        required_keys = {
            "delivery_id",
            "event_id",
            "event_type",
            "subscription_id",
            "target_url",
            "delivery_status",
            "attempts",
            "last_status_code",
            "last_error",
            "created_at",
            "updated_at",
            "delivered_at",
        }
        delivered_types: set[str] = set()
        for d in deliveries:
            if set(d.keys()) != required_keys:
                print(f"FAIL: delivery keys mismatch: {set(d.keys())}")
                return 1
            if d.get("delivery_status") == "DELIVERED":
                delivered_types.add(d.get("event_type"))

        if not {
            "INCIDENT_CREATED",
            "INCIDENT_STATUS_CHANGED",
            "AI_JOB_STATUS_CHANGED",
        }.issubset(seen_types):
            print(f"FAIL: missing event types: {seen_types}")
            return 1
        if "DELIVERED" not in {d.get("delivery_status") for d in deliveries}:
            print("FAIL: no DELIVERED deliveries")
            return 1
        if not {
            "INCIDENT_CREATED",
            "INCIDENT_STATUS_CHANGED",
            "AI_JOB_STATUS_CHANGED",
        }.issubset(delivered_types):
            print(f"FAIL: delivered types incomplete: {delivered_types}")
            return 1
        if args.fail_first_n > 0:
            max_attempts = max(int(d.get("attempts") or 0) for d in deliveries)
            if max_attempts < 2:
                print(f"FAIL: fail_first_n={args.fail_first_n} but max attempts={max_attempts} (expected >=2)")
                return 1
            if "DELIVERED" not in {d.get("delivery_status") for d in deliveries}:
                print("FAIL: fail_first_n>0 but no DELIVERED delivery")
                return 1
            print(f"max_attempts={max_attempts}")
        print("OK: outbound webhooks deliveries M9.5 passed.")
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
