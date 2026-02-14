#!/usr/bin/env python3
"""
M13.1 T3：context_ref 过长 -> 400。
构造 context_ref 长度 300+，POST /v1/ai/policy_suggest -> 400，PASS。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.1 T3: context_ref too long -> 400")
    parser.add_argument("--base_url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout
    session = requests.Session()

    r_boot = session.get(f"{base}/bootstrap", timeout=timeout)
    if r_boot.status_code != 200:
        print(f"FAIL: GET /bootstrap -> {r_boot.status_code}", file=sys.stderr)
        return 1
    print("bootstrap OK")

    long_ref = "x" * 301
    r = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None, "context_ref": long_ref},
        timeout=timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: expected 400 for context_ref len>256, got {r.status_code} {r.text}", file=sys.stderr)
        return 1
    print("PASS: context_ref length 301 -> 400")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
