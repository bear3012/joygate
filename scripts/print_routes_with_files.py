#!/usr/bin/env python3
from __future__ import annotations

import inspect

from joygate.main import app

def main() -> int:
    rows = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        endpoint = getattr(r, "endpoint", None)
        if not path or not methods or not endpoint:
            continue
        src = inspect.getsourcefile(endpoint) or ""
        rows.append((path, ",".join(sorted(methods)), getattr(endpoint, "__name__", ""), src))

    rows.sort(key=lambda x: x[0])
    for path, methods, name, src in rows:
        print(f"{methods:10s} {path:35s} {name:25s} {src}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
