#!/usr/bin/env python3
"""负例：创建订阅时内网/非法 target_url 必须返回 HTTP 400（target_url 校验，IP 字面量不依赖 DNS）。"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Webhook target_url 负例：内网 URL 应 400")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    session = requests.Session()

    r = session.get(f"{base}/bootstrap", timeout=args.timeout)
    if r.status_code != 200:
        print(f"FAIL: bootstrap {r.status_code}", file=sys.stderr)
        return 1

    cases = [
        "http://127.0.0.1:22/x",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
    ]
    for target_url in cases:
        payload = {
            "target_url": target_url,
            "event_types": ["INCIDENT_CREATED"],
            "secret": None,
            "is_enabled": True,
        }
        r = session.post(f"{base}/v1/webhooks/subscriptions", json=payload, timeout=args.timeout)
        if r.status_code != 400:
            print(f"FAIL: expected 400 for {target_url!r}, got {r.status_code} body={r.text}", file=sys.stderr)
            return 1
        print(f"OK: POST subscription target_url={target_url!r} -> 400")

    return 0


if __name__ == "__main__":
    sys.exit(main())
