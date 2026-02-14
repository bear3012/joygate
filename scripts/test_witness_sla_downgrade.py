from __future__ import annotations

import http.cookiejar
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _pick_port() -> int:
    ports = list(range(8015, 8099))
    random.shuffle(ports)
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port found in 8015-8099")


def _http_json(opener: urllib.request.OpenerDirector, method: str, url: str, body: dict | None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def _wait_bootstrap(opener: urllib.request.OpenerDirector, base_url: str, timeout_sec: float = 6.0) -> None:
    start = time.time()
    while True:
        try:
            status, _payload = _http_json(opener, "GET", f"{base_url}/bootstrap", None)
            if status == 200:
                return
        except Exception:
            pass
        if time.time() - start > timeout_sec:
            raise RuntimeError("bootstrap timeout")
        time.sleep(0.2)


def _find_incident(items: list[dict], incident_id: str) -> dict:
    for item in items:
        if item.get("incident_id") == incident_id:
            return item
    raise AssertionError(f"incident not found: {incident_id}")


def main() -> int:
    port = _pick_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["JOYGATE_WITNESS_SLA_TIMEOUT_MINUTES"] = "0.05"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "joygate.main:app", "--port", str(port), "--workers", "1"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        _wait_bootstrap(opener, base_url)

        status, payload = _http_json(
            opener,
            "POST",
            f"{base_url}/v1/incidents/report_blocked",
            {"charger_id": "charger-001", "incident_type": "BLOCKED"},
        )
        if status != 200 or "incident_id" not in payload:
            raise AssertionError(f"report_blocked failed: status={status}, payload={payload}")
        incident_id = payload["incident_id"]

        time.sleep(4)

        status, payload = _http_json(opener, "GET", f"{base_url}/v1/incidents", None)
        if status != 200:
            raise AssertionError(f"list_incidents failed: status={status}, payload={payload}")
        items = payload.get("incidents") or []
        inc = _find_incident(items, incident_id)

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
        if set(inc.keys()) != expected_keys:
            raise AssertionError(f"incident keys mismatch: {set(inc.keys())}")
        if inc.get("incident_status") != "UNDER_OBSERVATION":
            raise AssertionError(f"incident_status expected UNDER_OBSERVATION, got {inc.get('incident_status')!r}")

        insights = inc.get("ai_insights") or []
        sla_items = [i for i in insights if isinstance(i, dict) and i.get("insight_type") == "VISION_AUDIT_REQUESTED"]
        if len(sla_items) != 1:
            raise AssertionError(f"VISION_AUDIT_REQUESTED count expected 1, got {len(sla_items)}")

        status, payload = _http_json(opener, "GET", f"{base_url}/v1/incidents", None)
        if status != 200:
            raise AssertionError(f"list_incidents (second) failed: status={status}, payload={payload}")
        items = payload.get("incidents") or []
        inc = _find_incident(items, incident_id)
        insights = inc.get("ai_insights") or []
        sla_items = [i for i in insights if isinstance(i, dict) and i.get("insight_type") == "VISION_AUDIT_REQUESTED"]
        if len(sla_items) != 1:
            raise AssertionError(f"VISION_AUDIT_REQUESTED count expected 1 after second GET, got {len(sla_items)}")

        print("OK: witness SLA downgrade (8.2) passed.")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
