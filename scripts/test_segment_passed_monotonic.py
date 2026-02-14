"""
M10 segment_passed 乱序保护最小可复现测试：
先 POST 新事件（当前时间），再 POST 旧事件（时间 -120s），
断言 snapshot 中 cell_1_1 的 joykey/truth_input_source 仍为新事件的，last_passed_at 存在且非空。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="M10 segment_passed monotonic (out-of-order) test")
    parser.add_argument("--base_url", default="http://127.0.0.1:8010", help="Base URL of JoyGate API")
    parser.add_argument("--timeout_sec", type=float, default=5.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec
    session = requests.Session()

    # 第一步：GET bootstrap，提取 joygate_sandbox cookie
    bootstrap_url = f"{base}/bootstrap"
    try:
        r_boot = session.get(bootstrap_url, timeout=timeout)
    except requests.RequestException as e:
        print(f"bootstrap GET failed: {e}", file=sys.stderr)
        sys.exit(1)
    if r_boot.status_code != 200:
        print(f"bootstrap status {r_boot.status_code}", file=sys.stderr)
        sys.exit(1)
    sandbox = session.cookies.get("joygate_sandbox")
    if not sandbox:
        print("bootstrap did not set joygate_sandbox cookie", file=sys.stderr)
        sys.exit(1)
    print(f"bootstrap 200, cookie joygate_sandbox={sandbox}")

    # 第二步：POST 新事件
    ts_new = time.time()
    payload_new = {
        "joykey": "jk_new",
        "fleet_id": "fleetA",
        "segment_ids": ["cell_1_1"],
        "event_occurred_at": ts_new,
        "truth_input_source": "SIMULATOR",
    }
    url_segment = f"{base}/v1/telemetry/segment_passed"
    try:
        r_new = session.post(url_segment, json=payload_new, timeout=timeout)
    except requests.RequestException as e:
        print(f"segment_passed (new) POST failed: {e}", file=sys.stderr)
        sys.exit(1)
    if r_new.status_code != 204:
        print(f"segment_passed (new) expected 204, got {r_new.status_code} body={r_new.text}", file=sys.stderr)
        sys.exit(1)
    print(f"segment_passed (new) {r_new.status_code}")

    # 第三步：POST 旧事件（乱序）
    ts_old = ts_new - 120
    payload_old = {
        "joykey": "jk_old",
        "fleet_id": "fleetB",
        "segment_ids": ["cell_1_1"],
        "event_occurred_at": ts_old,
        "truth_input_source": "SIMULATOR",
    }
    try:
        r_old = session.post(url_segment, json=payload_old, timeout=timeout)
    except requests.RequestException as e:
        print(f"segment_passed (old) POST failed: {e}", file=sys.stderr)
        sys.exit(1)
    if r_old.status_code != 204:
        print(f"segment_passed (old) expected 204, got {r_old.status_code} body={r_old.text}", file=sys.stderr)
        sys.exit(1)
    print(f"segment_passed (old) {r_old.status_code}")

    # 第四步：GET snapshot，断言 cell_1_1 的 joykey / truth_input_source / last_passed_at
    snapshot_url = f"{base}/v1/snapshot"
    try:
        r_snap = session.get(snapshot_url, timeout=timeout)
    except requests.RequestException as e:
        print(f"snapshot GET failed: {e}", file=sys.stderr)
        sys.exit(1)
    if r_snap.status_code != 200:
        print(f"snapshot expected 200, got {r_snap.status_code}", file=sys.stderr)
        sys.exit(1)
    try:
        data = r_snap.json()
    except (ValueError, json.JSONDecodeError) as e:
        print(f"snapshot JSON decode failed: {e}", file=sys.stderr)
        sys.exit(1)

    signals = data.get("segment_passed_signals") or []
    cell_rec = None
    for s in signals:
        if isinstance(s, dict) and s.get("segment_id") == "cell_1_1":
            cell_rec = s
            break

    if not cell_rec:
        print("snapshot segment_passed_signals: no segment_id==cell_1_1", file=sys.stderr)
        print("signals (summary):", json.dumps(signals, ensure_ascii=False)[:500], file=sys.stderr)
        sys.exit(1)

    joykey = cell_rec.get("joykey")
    truth = cell_rec.get("truth_input_source")
    last_passed_at = cell_rec.get("last_passed_at")
    fleet_id = cell_rec.get("fleet_id")

    if joykey != "jk_new":
        print(f"assert joykey==jk_new failed: got {joykey!r}", file=sys.stderr)
        print("cell_1_1 record:", json.dumps(cell_rec, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if truth != "SIMULATOR":
        print(f"assert truth_input_source==SIMULATOR failed: got {truth!r}", file=sys.stderr)
        print("cell_1_1 record:", json.dumps(cell_rec, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if not (isinstance(last_passed_at, str) and last_passed_at.strip()):
        print(f"assert last_passed_at non-empty string failed: got {last_passed_at!r}", file=sys.stderr)
        print("cell_1_1 record:", json.dumps(cell_rec, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if fleet_id != "fleetA":
        print(f"assert fleet_id==fleetA failed: got {fleet_id!r}", file=sys.stderr)
        print("cell_1_1 record:", json.dumps(cell_rec, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    print(f"snapshot 200, cell_1_1 joykey={joykey} truth_input_source={truth} last_passed_at={last_passed_at} fleet_id={fleet_id}")
    print("OK segment_passed monotonic test passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
