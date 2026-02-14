#!/usr/bin/env python3
"""
M13.2 B2：敏感 context_ref 必须 400（需要服务）。
bootstrap -> POST /v1/ai/policy_suggest body {"context_ref":"Bearer abc.def.ghi"} -> 400，detail 含 looks sensitive。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="M13.2 B2: context_ref sensitive pattern -> 400")
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

    r = session.post(
        f"{base}/v1/ai/policy_suggest",
        json={"incident_id": None, "context_ref": "Bearer abc.def.ghi"},
        timeout=timeout,
    )
    if r.status_code != 400:
        print(f"FAIL: expected 400 for sensitive context_ref, got {r.status_code} {r.text}", file=sys.stderr)
        return 1
    detail = (r.json().get("detail") or r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
    if "looks sensitive" not in str(detail).lower():
        print(f"FAIL: detail should contain 'looks sensitive', got {detail!r}", file=sys.stderr)
        return 1
    print("PASS: context_ref sensitive pattern -> 400")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
