#!/usr/bin/env python3
"""
M8.3 Witness Voting 集成测试：同厂权重衰减（模型A）+ 双阈值确认。
使用 Python 标准库（urllib + subprocess），不依赖 requests。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen

DEFAULT_TIMEOUT = 5
HEALTH_CHECK_TIMEOUT = 5
PORT_RANGE_START = 8015
PORT_RANGE_END = 8099
PORT_MAX_ATTEMPTS = 20


def wait_for_health(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{base_url}/v1/snapshot", method="GET")
            with urlopen(req, timeout=2) as resp:
                if resp.getcode() == 200:
                    return True
        except (HTTPError, URLError, OSError, TimeoutError):
            pass
        time.sleep(0.2)
    return False


def get_json(opener, base_url: str, path: str, timeout: float) -> tuple[int, dict | None, str | None]:
    url = base_url.rstrip("/") + path
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return e.code, None, raw
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def post_json(
    opener, base_url: str, path: str, body: dict, timeout: float, extra_headers: dict | None = None
) -> tuple[int, dict | None, str | None]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=data, method="POST", headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else None, None
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw) if raw else None, None
        except json.JSONDecodeError:
            return e.code, None, raw
    except (URLError, OSError, TimeoutError) as e:
        return 0, None, str(e)


def find_incident(items: list[dict], incident_id: str) -> dict | None:
    for inc in items:
        if inc.get("incident_id") == incident_id:
            return inc
    return None


def assert_incident_shape(item: dict) -> None:
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
    if set(item.keys()) != expected_keys:
        raise AssertionError(f"incident keys mismatch: {set(item.keys())}")
    evidence_refs = item.get("evidence_refs") or []
    if len(evidence_refs) > 5:
        raise AssertionError(f"evidence_refs should be <= 5, got {len(evidence_refs)}")
    insights = item.get("ai_insights") or []
    if not any(isinstance(x, dict) and x.get("insight_type") == "WITNESS_TALLY" for x in insights):
        raise AssertionError("missing WITNESS_TALLY in ai_insights")


def extract_witness_tally_summary(item: dict) -> str:
    insights = item.get("ai_insights") or []
    for x in insights:
        if isinstance(x, dict) and x.get("insight_type") == "WITNESS_TALLY":
            summary = x.get("summary")
            if isinstance(summary, str) and summary:
                return summary
    raise AssertionError("missing WITNESS_TALLY summary")


def parse_witness_tally_summary(summary: str) -> dict:
    def _grab(pattern: str, cast):
        m = re.search(pattern, summary)
        if not m:
            return None
        return cast(m.group(1))

    return {
        "wFREE": _grab(r"wFREE=([0-9]+(?:\.[0-9]+)?)", float),
        "wOCCUPIED": _grab(r"wOCCUPIED=([0-9]+(?:\.[0-9]+)?)", float),
        "wUNKNOWN_OCCUPANCY": _grab(r"wUNKNOWN_OCCUPANCY=([0-9]+(?:\.[0-9]+)?)", float),
        "lead": _grab(r"lead=([A-Z_]+)", str),
        "lead_weighted": _grab(r"\bw=([0-9]+(?:\.[0-9]+)?)", float),
        "vendors": _grab(r"vendors=([0-9]+)", int),
        "gamma": _grab(r"gamma=([0-9]+(?:\.[0-9]+)?)", float),
    }


def require_witness_tally_summary_contract(incident_id: str, summary: str) -> None:
    if not isinstance(summary, str) or not summary:
        raise AssertionError(f"invalid summary: incident_id={incident_id}, summary={summary!r}")
    if not summary.startswith("witness tally:"):
        raise AssertionError(f"summary prefix mismatch: incident_id={incident_id}, summary={summary!r}")
    required_tokens = ["wOCCUPIED=", "lead=", "vendors=", "gamma="]
    for token in required_tokens:
        if token not in summary:
            raise AssertionError(
                f"summary missing token {token!r}: incident_id={incident_id}, summary={summary!r}"
            )
    if summary.count("|") < 2:
        raise AssertionError(f"summary missing segments: incident_id={incident_id}, summary={summary!r}")
    try:
        parsed = parse_witness_tally_summary(summary)
    except Exception as exc:
        raise AssertionError(
            f"summary parse error: incident_id={incident_id}, summary={summary!r}, error={exc}"
        ) from exc
    for key in ("lead", "vendors", "gamma", "wOCCUPIED"):
        if parsed.get(key) is None:
            raise AssertionError(
                f"summary parse missing {key}: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
            )
    if not isinstance(parsed.get("vendors"), int) or parsed["vendors"] < 1:
        raise AssertionError(
            f"vendors invalid: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
        )
    if not isinstance(parsed.get("gamma"), float) or not (0 < parsed["gamma"] <= 1):
        raise AssertionError(
            f"gamma invalid: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
        )
    if not isinstance(parsed.get("wOCCUPIED"), float) or parsed["wOCCUPIED"] < 0:
        raise AssertionError(
            f"wOCCUPIED invalid: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
        )


def assert_almost_equal(a: float | None, b: float, tol: float, msg: str) -> None:
    if a is None or abs(a - b) > tol:
        raise AssertionError(f"{msg} (got={a}, expected={b}, tol={tol})")


def assert_summary_fields(
    incident_id: str,
    summary: str,
    parsed: dict,
    *,
    vendors: int,
    gamma: float | None,
    lead: str,
    w_occupied: float | None,
    w_free: float | None = None,
    w_unknown: float | None = None,
    w_occupied_min: float | None = None,
    w_occupied_max: float | None = None,
) -> None:
    if parsed.get("vendors") != vendors:
        raise AssertionError(
            f"vendors mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
        )
    if gamma is not None:
        assert_almost_equal(
            parsed.get("gamma"),
            gamma,
            0.01,
            f"gamma mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}",
        )
    if parsed.get("lead") != lead:
        raise AssertionError(
            f"lead mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
        )
    if w_occupied is not None:
        assert_almost_equal(
            parsed.get("wOCCUPIED"),
            w_occupied,
            0.01,
            f"wOCCUPIED mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}",
        )
    if w_free is not None:
        assert_almost_equal(
            parsed.get("wFREE"),
            w_free,
            0.01,
            f"wFREE mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}",
        )
    if w_unknown is not None:
        assert_almost_equal(
            parsed.get("wUNKNOWN_OCCUPANCY"),
            w_unknown,
            0.01,
            f"wUNKNOWN_OCCUPANCY mismatch: incident_id={incident_id}, summary={summary!r}, parsed={parsed}",
        )
    if w_occupied_min is not None:
        if parsed.get("wOCCUPIED") is None or parsed["wOCCUPIED"] < w_occupied_min:
            raise AssertionError(
                f"wOCCUPIED too low: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
            )
    if w_occupied_max is not None:
        if parsed.get("wOCCUPIED") is None or parsed["wOCCUPIED"] > w_occupied_max:
            raise AssertionError(
                f"wOCCUPIED too high: incident_id={incident_id}, summary={summary!r}, parsed={parsed}"
            )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    robots_config = {
        "vendor_alpha": [{"joykey": "a1"}, {"joykey": "a2"}, {"joykey": "a3"}, {"joykey": "a4"}, {"joykey": "a5"}],
        "vendor_bravo": [{"joykey": "b1"}],
        "vendor_charlie": [{"joykey": "c1"}],
        "vendor_delta": [{"joykey": "d1"}],
        "vendor_echo": [{"joykey": "e1"}],
    }

    proc = None
    try:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["JOYGATE_WITNESS_ROBOTS_JSON"] = json.dumps(robots_config, ensure_ascii=True)
        env["JOYGATE_WITNESS_VENDOR_DECAY_GAMMA"] = "0.5"
        env["JOYGATE_WITNESS_MIN_DISTINCT_VENDORS"] = "2"
        env["JOYGATE_WITNESS_SCORE_REQUIRED"] = "2.0"
        env["JOYGATE_WITNESS_SCORE_REQUIRED_SINGLE_VENDOR"] = "1.9"
        env["JOYGATE_WITNESS_SLA_TIMEOUT_MINUTES"] = "0"

        ports = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
        random.shuffle(ports)
        base_url = None
        for port in ports[:PORT_MAX_ATTEMPTS]:
            base_url = f"http://127.0.0.1:{port}"
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "joygate.main:app", "--port", str(port), "--workers", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=repo_root,
            )
            if wait_for_health(base_url, HEALTH_CHECK_TIMEOUT):
                break
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            proc = None
        else:
            print(f"FAIL: service did not become healthy within {HEALTH_CHECK_TIMEOUT}s")
            return 1

        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))

        code, _, err = get_json(opener, base_url, "/bootstrap", DEFAULT_TIMEOUT)
        if code != 200 or err:
            print(f"FAIL: GET /bootstrap -> {code}, error={err}")
            return 1

        # 场景1：多厂商快速确认
        code, data, err = post_json(
            opener,
            base_url,
            "/v1/incidents/report_blocked",
            {"charger_id": "charger-001", "incident_type": "BLOCKED"},
            DEFAULT_TIMEOUT,
        )
        if code != 200 or err or not data or "incident_id" not in data:
            print(f"FAIL: report_blocked (scene1) -> {code}, error={err}, data={data}")
            return 1
        incident_id = data["incident_id"]

        for joykey in ["a1", "a2"]:
            code, _, err = post_json(
                opener,
                base_url,
                "/v1/witness/respond",
                {"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "OCCUPIED"},
                DEFAULT_TIMEOUT,
                extra_headers={"X-JoyKey": joykey},
            )
            if code != 204:
                print(f"FAIL: witness {joykey} -> {code}, error={err}")
                return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (scene1 pre-confirm) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id)
        if not item:
            print("FAIL: incident not found (scene1 pre-confirm)")
            return 1
        if item.get("incident_status") == "EVIDENCE_CONFIRMED":
            print("FAIL: scene1 should not be confirmed before second vendor")
            return 1
        summary = extract_witness_tally_summary(item)
        require_witness_tally_summary_contract(incident_id, summary)
        parsed = parse_witness_tally_summary(summary)
        assert_summary_fields(
            incident_id,
            summary,
            parsed,
            vendors=1,
            gamma=0.5,
            lead="OCCUPIED",
            w_occupied=1.50,
            w_free=0.00,
            w_unknown=0.00,
        )

        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {"incident_id": incident_id, "charger_id": "charger-001", "charger_state": "OCCUPIED"},
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "b1"},
        )
        if code != 204:
            print(f"FAIL: witness b1 -> {code}, error={err}")
            return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (scene1 confirm) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id)
        if not item:
            print("FAIL: incident not found (scene1 confirm)")
            return 1
        assert_incident_shape(item)
        if item.get("incident_status") != "EVIDENCE_CONFIRMED":
            print(f"FAIL: scene1 should be confirmed, got {item.get('incident_status')}")
            return 1
        summary = extract_witness_tally_summary(item)
        require_witness_tally_summary_contract(incident_id, summary)
        parsed = parse_witness_tally_summary(summary)
        assert_summary_fields(
            incident_id,
            summary,
            parsed,
            vendors=2,
            gamma=0.5,
            lead="OCCUPIED",
            w_occupied=2.50,
            w_free=0.00,
            w_unknown=0.00,
        )

        # 场景2：单厂商慢确认阈值 1.9
        code, data, err = post_json(
            opener,
            base_url,
            "/v1/incidents/report_blocked",
            {"charger_id": "charger-001", "incident_type": "BLOCKED"},
            DEFAULT_TIMEOUT,
        )
        if code != 200 or err or not data or "incident_id" not in data:
            print(f"FAIL: report_blocked (scene2) -> {code}, error={err}, data={data}")
            return 1
        incident_id2 = data["incident_id"]

        for joykey in ["a1", "a2", "a3", "a4"]:
            code, _, err = post_json(
                opener,
                base_url,
                "/v1/witness/respond",
                {"incident_id": incident_id2, "charger_id": "charger-001", "charger_state": "OCCUPIED"},
                DEFAULT_TIMEOUT,
                extra_headers={"X-JoyKey": joykey},
            )
            if code != 204:
                print(f"FAIL: witness {joykey} (scene2) -> {code}, error={err}")
                return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id2}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (scene2 pre-confirm) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id2)
        if not item:
            print("FAIL: incident not found (scene2 pre-confirm)")
            return 1
        if item.get("incident_status") == "EVIDENCE_CONFIRMED":
            print("FAIL: scene2 should not be confirmed before 5th vote")
            return 1
        summary = extract_witness_tally_summary(item)
        require_witness_tally_summary_contract(incident_id2, summary)
        parsed = parse_witness_tally_summary(summary)
        assert_summary_fields(
            incident_id2,
            summary,
            parsed,
            vendors=1,
            gamma=None,
            lead="OCCUPIED",
            w_occupied=1.88,
            w_free=0.00,
            w_unknown=0.00,
            w_occupied_max=1.89,
        )

        code, _, err = post_json(
            opener,
            base_url,
            "/v1/witness/respond",
            {"incident_id": incident_id2, "charger_id": "charger-001", "charger_state": "OCCUPIED"},
            DEFAULT_TIMEOUT,
            extra_headers={"X-JoyKey": "a5"},
        )
        if code != 204:
            print(f"FAIL: witness a5 (scene2) -> {code}, error={err}")
            return 1

        code, data, err = get_json(opener, base_url, f"/v1/incidents?incident_id={incident_id2}", DEFAULT_TIMEOUT)
        if code != 200 or err or not data:
            print(f"FAIL: GET /v1/incidents (scene2 confirm) -> {code}, error={err}")
            return 1
        item = find_incident(data.get("incidents") or [], incident_id2)
        if not item:
            print("FAIL: incident not found (scene2 confirm)")
            return 1
        assert_incident_shape(item)
        if item.get("incident_status") != "EVIDENCE_CONFIRMED":
            print(f"FAIL: scene2 should be confirmed, got {item.get('incident_status')}")
            return 1
        summary = extract_witness_tally_summary(item)
        require_witness_tally_summary_contract(incident_id2, summary)
        parsed = parse_witness_tally_summary(summary)
        assert_summary_fields(
            incident_id2,
            summary,
            parsed,
            vendors=1,
            gamma=None,
            lead="OCCUPIED",
            w_occupied=1.94,
            w_free=0.00,
            w_unknown=0.00,
            w_occupied_min=1.90,
        )

        print("OK: witness vendor weight + dual threshold (8.3) passed.")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
