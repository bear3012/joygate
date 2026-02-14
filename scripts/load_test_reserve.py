#!/usr/bin/env python3
# scripts/load_test_reserve.py
"""
并发压测 JoyGate /v1/reserve，仅用标准库，不引入第三方依赖。

Schema 兼容：若解析 /v1/snapshot，仅依赖 hold_id/charger_id/joykey/expires_at 及 chargers.slot_state
等核心字段；忽略扩展字段（is_priority_compensated/compensation_reason/queue_position_drift/incident_id）。

安全审计说明（Security Audit）：
- 本脚本用于发现并发一致性漏洞：双占位、规则绕过、状态崩坏。
- 不对服务做破坏性动作（无无限循环、不刷爆资源）。
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse

REQUEST_TIMEOUT = 3
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1/reserve"
DEFAULT_N = 50
MAX_SAMPLE_UNEXPECTED = 5
MAX_SAMPLE_200 = 3


def _post_reserve(base_url: str, body: dict, timeout: float = REQUEST_TIMEOUT) -> tuple[int, str]:
    """发 POST /v1/reserve，返回 (status_code, response_body_str)。"""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_read = e.read().decode("utf-8", errors="replace")
        return e.code, body_read
    except Exception as e:
        return -1, str(e)


def _derive_stop_url(base_url: str) -> str:
    """从 base_url 推导同域名的 /v1/oracle/stop_charging。"""
    p = urlparse(base_url)
    return urlunparse(p._replace(path="/v1/oracle/stop_charging"))


def _derive_snapshot_url(base_url: str) -> str:
    """从 base_url 推导同域名的 /v1/snapshot。"""
    p = urlparse(base_url)
    return urlunparse(p._replace(path="/v1/snapshot"))


def _get_snapshot(snapshot_url: str, timeout: float = REQUEST_TIMEOUT) -> tuple[int, str]:
    """GET /v1/snapshot，返回 (status_code, response_body_str)。"""
    req = urllib.request.Request(snapshot_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return -1, str(e)


def _check_snapshot_core_invariants(snapshot_json: dict) -> list[str]:
    """
    检查 snapshot 核心不变量 + M2 HoldSnapshot 新增字段默认值。
    返回 errors 列表；空列表表示通过。只用 .get()，不因未知字段失败。
    """
    errors: list[str] = []

    # snapshot_at 必须是字符串
    snapshot_at = snapshot_json.get("snapshot_at")
    if not isinstance(snapshot_at, str):
        errors.append(f"snapshot_at expected str, got {type(snapshot_at).__name__}")

    # chargers 必须是 list
    chargers = snapshot_json.get("chargers")
    if not isinstance(chargers, list):
        errors.append(f"chargers expected list, got {type(chargers).__name__}")
    else:
        for i, c in enumerate(chargers):
            if not isinstance(c, dict):
                errors.append(f"chargers[{i}] expected dict, got {type(c).__name__}")
                continue
            cid = c.get("charger_id")
            if not isinstance(cid, str):
                errors.append(f"chargers[{i}].charger_id expected str, got {type(cid).__name__}")
            slot_state = c.get("slot_state")
            if not isinstance(slot_state, str):
                errors.append(f"chargers[{i}].slot_state expected str, got {type(slot_state).__name__}")

    # holds 必须是 list
    holds = snapshot_json.get("holds")
    if not isinstance(holds, list):
        errors.append(f"holds expected list, got {type(holds).__name__}")
    else:
        if len(holds) == 0:
            # holds 为空：打印 warning，不失败
            print("warning: snapshot holds is empty, skipping M2 new fields validation")
        for i, h in enumerate(holds):
            if not isinstance(h, dict):
                errors.append(f"holds[{i}] expected dict, got {type(h).__name__}")
                continue
            # 核心字段：hold_id/charger_id/joykey/expires_at
            for field in ("hold_id", "charger_id", "joykey", "expires_at"):
                val = h.get(field)
                if not isinstance(val, str):
                    errors.append(f"holds[{i}].{field} expected str, got {type(val).__name__}")
            # M2 新增 4 字段默认值检查
            # is_priority_compensated == False
            ipc = h.get("is_priority_compensated")
            if ipc is not False:
                errors.append(f"holds[{i}].is_priority_compensated expected False, got {ipc!r}")
            # compensation_reason == None
            cr = h.get("compensation_reason")
            if cr is not None:
                errors.append(f"holds[{i}].compensation_reason expected None, got {cr!r}")
            # queue_position_drift == None
            qpd = h.get("queue_position_drift")
            if qpd is not None:
                errors.append(f"holds[{i}].queue_position_drift expected None, got {qpd!r}")
            # incident_id == None
            iid = h.get("incident_id")
            if iid is not None:
                errors.append(f"holds[{i}].incident_id expected None, got {iid!r}")

    return errors


def _post_stop_charging(stop_url: str, hold_id: str, charger_id: str, timeout: float = REQUEST_TIMEOUT) -> tuple[int, str]:
    """POST stop_charging，body 符合 FIELD_REGISTRY OracleStopCharging。返回 (status_code, response_body)。"""
    body = {
        "hold_id": hold_id,
        "charger_id": charger_id,
        "meter_session_id": "loadtest",
        "event_occurred_at": "2026-01-30T00:00:00Z",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        stop_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return -1, str(e)


def run_same_joykey(base_url: str, n: int) -> list[tuple[int, str, str]]:
    """N 个并发：同一 joykey，不同 resource_id（charger-001..010 循环）。返回 (code, body, resource_id)。"""
    joykey = "load_test_same_joykey"
    results = []

    def do_one(i: int) -> tuple[int, str, str]:
        resource_id = f"charger-{(i % 10) + 1:03d}"
        body = {
            "resource_type": "charger",
            "resource_id": resource_id,
            "joykey": joykey,
            "action": "HOLD",
        }
        code, resp_body = _post_reserve(base_url, body)
        return code, resp_body, resource_id

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(do_one, i) for i in range(n)]
        for f in as_completed(futures):
            results.append(f.result())
    return results


def run_same_charger(base_url: str, n: int) -> list[tuple[int, str, str]]:
    """N 个并发：不同 joykey，同一 resource_id（charger-001）。返回 (code, body, resource_id)。"""
    resource_id = "charger-001"
    results = []

    def do_one(i: int) -> tuple[int, str, str]:
        joykey = f"load_test_same_charger_{i}"
        body = {
            "resource_type": "charger",
            "resource_id": resource_id,
            "joykey": joykey,
            "action": "HOLD",
        }
        code, resp_body = _post_reserve(base_url, body)
        return code, resp_body, resource_id

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(do_one, i) for i in range(n)]
        for f in as_completed(futures):
            results.append(f.result())
    return results


def run_mix(base_url: str, n: int) -> list[tuple[int, str, str]]:
    """一半 same_joykey 风格，一半 same_charger 风格。返回 (code, body, resource_id)。"""
    half = n // 2
    results = []

    def same_joykey_task(i: int) -> tuple[int, str, str]:
        joykey = "load_test_mix_joykey"
        resource_id = f"charger-{(i % 10) + 1:03d}"
        body = {
            "resource_type": "charger",
            "resource_id": resource_id,
            "joykey": joykey,
            "action": "HOLD",
        }
        code, resp_body = _post_reserve(base_url, body)
        return code, resp_body, resource_id

    def same_charger_task(i: int) -> tuple[int, str, str]:
        joykey = f"load_test_mix_charger_{i}"
        resource_id = "charger-001"
        body = {
            "resource_type": "charger",
            "resource_id": resource_id,
            "joykey": joykey,
            "action": "HOLD",
        }
        code, resp_body = _post_reserve(base_url, body)
        return code, resp_body, resource_id

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = []
        for i in range(half):
            futures.append(ex.submit(same_joykey_task, i))
        for i in range(half, n):
            futures.append(ex.submit(same_charger_task, i))
        for f in as_completed(futures):
            results.append(f.result())
    return results


def count_codes(results: list[tuple[int, str, str]]) -> dict[int, int]:
    c: dict[int, int] = {}
    for code, _, _ in results:
        c[code] = c.get(code, 0) + 1
    return c


def sample_unexpected(
    results: list[tuple[int, str, str]], expected_codes: set[int], max_sample: int
) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for code, body, _ in results:
        if code not in expected_codes or code < 0:
            out.append((code, body))
            if len(out) >= max_sample:
                break
    return out


def collect_cleanup_tasks(
    results: list[tuple[int, str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[int, str]]]:
    """从 200 响应中提取 (hold_id, charger_id)；解析失败或无 hold_id 的 200 纳入 invalid_200 供 unexpected 展示。"""
    cleanup_tasks: list[tuple[str, str]] = []
    invalid_200: list[tuple[int, str]] = []
    for code, body, resource_id in results:
        if code != 200:
            continue
        try:
            data = json.loads(body)
            hold_id = data.get("hold_id") if isinstance(data, dict) else None
            if hold_id:
                cleanup_tasks.append((hold_id, resource_id))
            else:
                invalid_200.append((200, body))
        except (json.JSONDecodeError, TypeError):
            invalid_200.append((200, body))
    return cleanup_tasks, invalid_200


def main() -> None:
    parser = argparse.ArgumentParser(description="JoyGate /v1/reserve 并发压测")
    parser.add_argument("--case", choices=["same_joykey", "same_charger", "mix"], required=True, help="测试场景")
    parser.add_argument("--base_url", default=DEFAULT_BASE_URL, help="reserve 接口 base URL")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="并发请求数")
    parser.add_argument(
        "--cleanup",
        default="true",
        choices=("true", "false"),
        help="压测后是否 POST stop_charging 清理占位（默认 true）",
    )
    parser.add_argument("--stop_url", default="", help="stop_charging URL，未提供则从 base_url 推导")
    parser.add_argument(
        "--check_snapshot",
        default="false",
        choices=("true", "false"),
        help="压测后是否 GET /v1/snapshot 并验证核心不变量 + M2 新增字段（默认 false）",
    )
    parser.add_argument("--snapshot_url", default="", help="snapshot URL，未提供则从 base_url 推导")
    args = parser.parse_args()

    case = args.case
    base_url = args.base_url.rstrip("/")
    n = args.n
    do_cleanup = args.cleanup == "true"
    stop_url = args.stop_url.strip() if args.stop_url else _derive_stop_url(base_url)
    do_check_snapshot = args.check_snapshot == "true"
    snapshot_url = args.snapshot_url.strip() if args.snapshot_url else _derive_snapshot_url(base_url)

    start = time.perf_counter()
    if case == "same_joykey":
        results = run_same_joykey(base_url, n)
    elif case == "same_charger":
        results = run_same_charger(base_url, n)
    else:
        results = run_mix(base_url, n)
    elapsed = time.perf_counter() - start

    codes = count_codes(results)
    code_200 = codes.get(200, 0)
    code_409 = codes.get(409, 0)
    code_429 = codes.get(429, 0)
    other = sum(v for k, v in codes.items() if k not in (200, 409, 429))

    print(f"case={case} n={n} elapsed_sec={elapsed:.3f}")
    print(f"status: 200={code_200} 409={code_409} 429={code_429} other={other}")

    cleanup_tasks, invalid_200 = collect_cleanup_tasks(results)

    # 抽样打印最多 3 条 200 响应（截断 200 字符）
    sample_200 = [(code, body) for code, body, _ in results if code == 200][:MAX_SAMPLE_200]
    if sample_200:
        print("sample 200 (max 3):")
        for code, body in sample_200:
            snippet = (body[:200] + "…") if len(body) > 200 else body
            print(f"  [{code}] {snippet}")

    expected_codes = {200, 429} if case == "same_joykey" else {200, 409} if case == "same_charger" else {200, 409, 429}
    unexpected = sample_unexpected(results, expected_codes, MAX_SAMPLE_UNEXPECTED)
    for item in invalid_200:
        if item not in unexpected and len(unexpected) < MAX_SAMPLE_UNEXPECTED:
            unexpected.append(item)
    unexpected = unexpected[:MAX_SAMPLE_UNEXPECTED]
    if unexpected:
        print("sample unexpected (max 5):")
        for code, body in unexpected:
            snippet = (body[:200] + "…") if len(body) > 200 else body
            print(f"  [{code}] {snippet}")

    ok = True
    if case == "same_joykey":
        if code_200 != 1 or code_429 != n - 1:
            ok = False
    elif case == "same_charger":
        if code_200 != 1 or code_409 != n - 1:
            ok = False
    else:
        if other != 0 or not (1 <= code_200 <= 2):
            ok = False

    # --check_snapshot: 在 cleanup 前 GET snapshot 并验证核心不变量 + M2 新增字段
    if do_check_snapshot:
        snap_code, snap_body = _get_snapshot(snapshot_url)
        if snap_code != 200:
            print(f"snapshot_check=FAIL status={snap_code}")
            ok = False
        else:
            try:
                snap_json = json.loads(snap_body)
            except json.JSONDecodeError as e:
                print(f"snapshot_check=FAIL json_error={e}")
                ok = False
                snap_json = None
            if snap_json is not None:
                snap_errors = _check_snapshot_core_invariants(snap_json)
                if snap_errors:
                    print(f"snapshot_check=FAIL errors={len(snap_errors)}")
                    for err in snap_errors[:10]:
                        print(f"  - {err}")
                    ok = False
                else:
                    print("snapshot_check=PASS")

    if do_cleanup and cleanup_tasks:
        for hold_id, charger_id in cleanup_tasks:
            try:
                sc, _ = _post_stop_charging(stop_url, hold_id, charger_id)
                if sc != 200:
                    print(f"warning: stop_charging {hold_id} @ {charger_id} -> status {sc}")
            except Exception as e:
                print(f"warning: stop_charging {hold_id} @ {charger_id} -> {e!r}")

    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
