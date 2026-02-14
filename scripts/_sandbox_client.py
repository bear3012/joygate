from __future__ import annotations

from typing import Any

import requests


def get_bootstrapped_session(base_url: str, timeout_sec: float) -> requests.Session:
    """
    创建 requests.Session 并完成 /bootstrap，确保拿到 joygate_sandbox cookie。
    """
    session = requests.Session()
    url = base_url.rstrip("/") + "/bootstrap"
    try:
        resp = session.get(url, timeout=timeout_sec)
    except requests.RequestException as e:
        raise RuntimeError(f"bootstrap request failed: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"bootstrap status unexpected: {resp.status_code}")

    try:
        data: Any = resp.json()
    except ValueError as e:
        raise RuntimeError(f"bootstrap response not JSON: {e}") from e

    if not isinstance(data, dict):
        raise RuntimeError("bootstrap response not a JSON object")

    sandbox_id = data.get("sandbox_id")
    note = data.get("note")
    if sandbox_id is None or (isinstance(note, str) and "capacity reached" in note):
        raise RuntimeError("sandbox capacity reached; restart service or increase JOYGATE_MAX_SANDBOXES")

    cookie_val = session.cookies.get("joygate_sandbox")
    if not cookie_val:
        raise RuntimeError(
            "missing joygate_sandbox cookie; possible sandbox capacity reached, restart service or increase JOYGATE_MAX_SANDBOXES"
        )

    return session
