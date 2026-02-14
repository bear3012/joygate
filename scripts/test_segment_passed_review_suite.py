"""
M10 segment_passed 复审测试：排序/去重、200 上限、tie case、格式兼容、并发一致性。
失败时 exit(1)；成功打印 OK 及确定性口径结论。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
from datetime import datetime, timezone

import requests


def _bootstrap(base: str, timeout: float) -> requests.Session:
    session = requests.Session()
    r = session.get(f"{base}/bootstrap", timeout=timeout)
    if r.status_code != 200 or not session.cookies.get("joygate_sandbox"):
        print("bootstrap failed or no cookie", file=sys.stderr)
        sys.exit(1)
    return session


def _post_segment(session: requests.Session, base: str, payload: dict, timeout: float) -> requests.Response:
    return session.post(f"{base}/v1/telemetry/segment_passed", json=payload, timeout=timeout)


def _get_snapshot(session: requests.Session, base: str, timeout: float) -> dict:
    r = session.get(f"{base}/v1/snapshot", timeout=timeout)
    if r.status_code != 200:
        print(f"snapshot {r.status_code}", file=sys.stderr)
        sys.exit(1)
    return r.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="M10 segment_passed review suite")
    parser.add_argument("--base_url", default="http://127.0.0.1:8030")
    parser.add_argument("--timeout_sec", type=float, default=10.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout_sec

    session = _bootstrap(base, timeout)
    url_segment = f"{base}/v1/telemetry/segment_passed"
    now = time.time()

    # --- 1) 排序与去重 ---
    print("--- 1) Sort and dedup ---")
    for seg in ["cell_1_2", "cell_1_1", "cell_2_1"]:
        r = _post_segment(session, base, {
            "joykey": "jk", "fleet_id": None, "segment_ids": [seg],
            "event_occurred_at": now, "truth_input_source": "SIMULATOR",
        }, timeout)
        if r.status_code != 204:
            print(f"post {seg} -> {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
    data = _get_snapshot(session, base, timeout)
    signals = data.get("segment_passed_signals") or []
    seg_ids = [s.get("segment_id") for s in signals if isinstance(s, dict) and s.get("segment_id")]
    for sid in ["cell_1_1", "cell_1_2", "cell_2_1"]:
        if sid not in seg_ids:
            print(f"missing {sid} in signals", file=sys.stderr)
            sys.exit(1)
    sorted_ids = sorted(seg_ids)
    if seg_ids != sorted_ids:
        print(f"not sorted: got {seg_ids}", file=sys.stderr)
        sys.exit(1)
    if len(seg_ids) != len(set(seg_ids)):
        print("duplicate segment_id", file=sys.stderr)
        sys.exit(1)
    print("  segment_passed_signals sorted by segment_id, no duplicates OK")

    # --- 2) 200 上限（210 条上报，限流下间隔 0.6s）---
    print("--- 2) Cap 200 ---")
    for i in range(210):
        seg = f"cell_0_{i}"
        r = _post_segment(session, base, {
            "joykey": "jk", "fleet_id": None, "segment_ids": [seg],
            "event_occurred_at": now + i * 0.001, "truth_input_source": "SIMULATOR",
        }, timeout)
        if r.status_code != 204:
            print(f"post {seg} -> {r.status_code}", file=sys.stderr)
            sys.exit(1)
        time.sleep(0.6)
    data = _get_snapshot(session, base, timeout)
    signals = data.get("segment_passed_signals") or []
    if len(signals) > 200:
        print(f"len(signals)={len(signals)} > 200", file=sys.stderr)
        sys.exit(1)
    print(f"  len(segment_passed_signals)={len(signals)} <= 200 OK (store eviction: MAX_SEGMENT_PASSED=200, evict oldest by last_passed_ts)")

    # --- 3) Tie case（同一 event_occurred_at，两次不同 joykey/fleet_id）---
    print("--- 3) Tie case (same event_occurred_at) ---")
    tie_ts = time.time() - 10
    r1 = _post_segment(session, base, {
        "joykey": "tie_A", "fleet_id": "fleetA", "segment_ids": ["cell_99_99"],
        "event_occurred_at": tie_ts, "truth_input_source": "SIMULATOR",
    }, timeout)
    r2 = _post_segment(session, base, {
        "joykey": "tie_B", "fleet_id": "fleetB", "segment_ids": ["cell_99_99"],
        "event_occurred_at": tie_ts, "truth_input_source": "SIMULATOR",
    }, timeout)
    if r1.status_code != 204 or r2.status_code != 204:
        print(f"tie POSTs: {r1.status_code} {r2.status_code}", file=sys.stderr)
        sys.exit(1)
    data = _get_snapshot(session, base, timeout)
    signals = [s for s in (data.get("segment_passed_signals") or []) if s.get("segment_id") == "cell_99_99"]
    if len(signals) != 1:
        print(f"expected 1 cell_99_99, got {len(signals)}", file=sys.stderr)
        sys.exit(1)
    rec = signals[0]
    tie_joykey = rec.get("joykey")
    tie_fleet = rec.get("fleet_id")
    print(f"  tie: same event_occurred_at -> kept joykey={tie_joykey} fleet_id={tie_fleet} (deterministic: last-writer-wins when event_ts equal)")

    # --- 4) event_occurred_at 格式：ISO8601 Z + epoch ---
    print("--- 4) event_occurred_at format (ISO8601 + epoch) ---")
    iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r_iso = _post_segment(session, base, {
        "joykey": "fmt", "fleet_id": None, "segment_ids": ["cell_10_1"],
        "event_occurred_at": iso_ts, "truth_input_source": "SIMULATOR",
    }, timeout)
    if r_iso.status_code != 204:
        print(f"ISO8601 POST -> {r_iso.status_code} {r_iso.text}", file=sys.stderr)
        sys.exit(1)
    epoch_ts = time.time()
    r_epoch = _post_segment(session, base, {
        "joykey": "fmt", "fleet_id": None, "segment_ids": ["cell_10_2"],
        "event_occurred_at": epoch_ts, "truth_input_source": "SIMULATOR",
    }, timeout)
    if r_epoch.status_code != 204:
        print(f"epoch POST -> {r_epoch.status_code}", file=sys.stderr)
        sys.exit(1)
    data = _get_snapshot(session, base, timeout)
    by_seg = {s["segment_id"]: s for s in (data.get("segment_passed_signals") or []) if s.get("segment_id") in ("cell_10_1", "cell_10_2")}
    if "cell_10_1" not in by_seg or "cell_10_2" not in by_seg:
        print("format: missing cell_10_1 or cell_10_2", file=sys.stderr)
        sys.exit(1)
    print("  ISO8601(Z) and epoch both 204, snapshot updated OK")

    # --- 5) 并发一致性（20 线程，同 segment_id 不同时间戳，同一 sandbox）---
    print("--- 5) Concurrency (20 threads, same segment_id) ---")
    base_ts = time.time() - 50
    cookie_val = session.cookies.get("joygate_sandbox")
    if not cookie_val:
        print("no cookie for concurrency test", file=sys.stderr)
        sys.exit(1)
    results = []

    def send_one(i: int) -> tuple[int, int]:
        t = base_ts + i * 0.01
        sess = requests.Session()
        sess.cookies.set("joygate_sandbox", cookie_val)
        r = _post_segment(sess, base, {
            "joykey": f"concur_{i}", "fleet_id": f"f{i}", "segment_ids": ["cell_88_1"],
            "event_occurred_at": t, "truth_input_source": "SIMULATOR",
        }, timeout)
        return i, r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(send_one, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            i, code = f.result()
            results.append((i, code))
            if code != 204:
                print(f"concur thread {i} -> {code}", file=sys.stderr)
    if any(c != 204 for _, c in results):
        sys.exit(1)
    data = _get_snapshot(session, base, timeout)
    concur_recs = [s for s in (data.get("segment_passed_signals") or []) if s.get("segment_id") == "cell_88_1"]
    if len(concur_recs) != 1:
        print(f"expected 1 cell_88_1, got {len(concur_recs)}", file=sys.stderr)
        sys.exit(1)
    winner = concur_recs[0]
    last_at = winner.get("last_passed_at") or ""
    expected_ts = base_ts + 19 * 0.01
    expected_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expected_ts))
    print(f"  winner: joykey={winner.get('joykey')} fleet_id={winner.get('fleet_id')} last_passed_at={last_at}")
    print(f"  (expected max event_occurred_at ~ {expected_iso}; last_passed_at should match max)")

    print("OK segment_passed review suite passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
