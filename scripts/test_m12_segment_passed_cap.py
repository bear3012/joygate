from __future__ import annotations

import time

from joygate.store import JoyGateStore


def main() -> None:
    store = JoyGateStore()
    base = time.time()

    joykey = "robot_cap"
    for i in range(250):
        store.record_segment_passed(f"cell_{i}_0", base + i, joykey, "sim")

    seg = store._segment_passed  # type: ignore[attr-defined]
    if not isinstance(seg, dict):
        raise SystemExit("FAIL: store._segment_passed missing")
    if len(seg) != 200:
        raise SystemExit(f"FAIL: segment_passed cap expected 200, got={len(seg)}")

    # 250-200=50，应淘汰最早的 cell_0_0...cell_49_0
    for i in range(50):
        if f"cell_{i}_0" in seg:
            raise SystemExit(f"FAIL: expected old segment to be evicted: cell_{i}_0")
    # 应保留从 cell_50_0 到 cell_249_0（至少边界要在）
    if "cell_50_0" not in seg or "cell_249_0" not in seg:
        raise SystemExit("FAIL: expected kept segments missing")

    signals = store.list_segment_passed_signals(limit=500)
    if len(signals) != 200:
        raise SystemExit(f"FAIL: list_segment_passed_signals expected 200, got={len(signals)}")

    print("PASS: T3 segment_passed cap=200 evicts oldest by last_passed_ts")


if __name__ == "__main__":
    main()
