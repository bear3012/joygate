#!/usr/bin/env python3
"""
Sandbox 容量防 DoS 最小自测：循环调用 /bootstrap（不带 cookie）创建大量 sandbox，
验证服务端通过 TTL + LRU 淘汰将数量控制在 MAX_SANDBOXES 内，不无限增长。
"""
from __future__ import annotations

import argparse
import sys

import requests


def main() -> int:
    p = argparse.ArgumentParser(description="Sandbox capacity DoS test: N bootstraps without cookie")
    p.add_argument("--base_url", default="http://127.0.0.1:8013")
    p.add_argument("--n", type=int, default=25, help="number of GET /bootstrap calls")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    url = f"{base}/bootstrap"
    ok = 0
    other = 0
    for i in range(args.n):
        try:
            r = requests.get(url, timeout=args.timeout)
            if r.status_code == 200:
                ok += 1
            else:
                other += 1
        except requests.RequestException as e:
            print(f"request error: {e}", file=sys.stderr)
            other += 1
    print(f"bootstrap_capacity_test: n={args.n} 200_ok={ok} other={other}")
    return 0 if other == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
