"""乱序上报自测：先 POST 较新 event_occurred_at，再 POST 更旧（同 segment），
GET snapshot 断言 last_passed_at 不变且 joykey 仍是第一次。"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")
from _sandbox_client import get_bootstrapped_session

BASE = "http://127.0.0.1:8000"

def main():
    session = get_bootstrapped_session(BASE, 10.0)
    now = time.time()
    # 1) 先 POST 较新的 event_occurred_at（joykey=first_joykey）
    r1 = session.post(
        BASE + "/v1/telemetry/segment_passed",
        json={
            "joykey": "first_joykey",
            "fleet_id": None,
            "segment_ids": ["cell_oo_1"],
            "event_occurred_at": now - 2,
            "truth_input_source": "SIMULATOR",
        },
        timeout=10,
    )
    assert r1.status_code == 204, r1.status_code
    # 2) GET snapshot 取第一次的 last_passed_at 和 joykey
    r2 = session.get(BASE + "/v1/snapshot", timeout=10)
    assert r2.status_code == 200
    data = r2.json()
    signals = {s["segment_id"]: s for s in data.get("segment_passed_signals") or []}
    assert "cell_oo_1" in signals, signals
    first_at = signals["cell_oo_1"]["last_passed_at"]
    first_joykey = signals["cell_oo_1"]["joykey"]
    print("After first POST (newer ts): last_passed_at=%s joykey=%s" % (first_at, first_joykey))
    # 3) 再 POST 更旧的 event_occurred_at（同 segment，joykey=second_joykey）
    r3 = session.post(
        BASE + "/v1/telemetry/segment_passed",
        json={
            "joykey": "second_joykey",
            "fleet_id": None,
            "segment_ids": ["cell_oo_1"],
            "event_occurred_at": now - 100,
            "truth_input_source": "SIMULATOR",
        },
        timeout=10,
    )
    assert r3.status_code == 204, r3.status_code
    # 4) GET snapshot 断言 last_passed_at 不变、joykey 仍是第一次
    r4 = session.get(BASE + "/v1/snapshot", timeout=10)
    assert r4.status_code == 200
    data2 = r4.json()
    signals2 = {s["segment_id"]: s for s in data2.get("segment_passed_signals") or []}
    after_at = signals2["cell_oo_1"]["last_passed_at"]
    after_joykey = signals2["cell_oo_1"]["joykey"]
    print("After second POST (older ts): last_passed_at=%s joykey=%s" % (after_at, after_joykey))
    assert after_at == first_at, "last_passed_at should not change: %s -> %s" % (first_at, after_at)
    assert after_joykey == "first_joykey", "joykey should stay first_joykey, got %s" % after_joykey
    print("OK: out-of-order test passed. last_passed_at unchanged, joykey remains first_joykey.")


if __name__ == "__main__":
    main()
