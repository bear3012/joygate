from __future__ import annotations

import time

from joygate.store import JoyGateStore


def main() -> None:
    store = JoyGateStore()

    joykey = "robot_ring"
    base = time.time()

    # 非法 segment_id 不应进入轨迹
    store.record_segment_passed("segA", base + 0, joykey, "sim")
    store.record_segment_passed("cell_1_a", base + 1, joykey, "sim")
    store.record_segment_passed("cell__1_2", base + 2, joykey, "sim")

    tracks = store._robot_tracks.get(joykey)  # type: ignore[attr-defined]
    if tracks:
        raise SystemExit(f"FAIL: invalid segment_id should not be tracked, got={tracks}")

    # 追加 60 个合法 cell_x_y，应只保留最近 50 个
    for i in range(60):
        store.record_segment_passed(f"cell_{i}_0", base + 10 + i, joykey, "sim")

    tracks = store._robot_tracks.get(joykey)  # type: ignore[attr-defined]
    if not isinstance(tracks, list):
        raise SystemExit("FAIL: tracks missing")

    if len(tracks) != 50:
        raise SystemExit(f"FAIL: ring buffer size expected 50, got={len(tracks)}")

    # 60 条里应丢掉最早的 10 条，保留 cell_10_0 ... cell_59_0
    if tracks[0] != "cell_10_0" or tracks[-1] != "cell_59_0":
        raise SystemExit(f"FAIL: ring buffer window mismatch, head={tracks[0]!r}, tail={tracks[-1]!r}")

    print("PASS: T1 tracks ring buffer + cell_x_y only")


if __name__ == "__main__":
    main()
