from __future__ import annotations

from typing import Any, Callable


def build_incidents_daily_report(
    copy_list: list[dict[str, Any]],
    now_ts: float,
    boot_ts: float,
    day_mode: str,
    demo_day_seconds: int | None,
    tz_offset_hours: int,
    incident_stale_minutes: int,
    severe_incident_statuses: set[str],
    date_str_with_offset: Callable[[float, int], str],
) -> dict[str, Any]:
    # 全量未解决（不看日期）
    unresolved = [r for r in copy_list if r.get("incident_status") != "RESOLVED"]

    # 计算今日 resolved_today 与 today_date（根据 DASHBOARD_DAY_MODE 分支）
    resolved_today: list[dict[str, Any]] = []
    demo_day_index: int | None = None

    if day_mode == "DEMO":
        # Demo Clock：boot_ts 起算，DEMO_DAY_SECONDS 为一日长度
        demo_sec = demo_day_seconds or 300
        demo_day_index = int((now_ts - boot_ts) // demo_sec) + 1
        day_start = boot_ts + (demo_day_index - 1) * demo_sec
        day_end = day_start + demo_sec
        today_date = f"DEMO_DAY_{demo_day_index}"

        for r in copy_list:
            if r.get("incident_status") == "RESOLVED":
                base_ts = r.get("status_updated_at") or r.get("created_at", 0.0)
                if day_start <= base_ts < day_end:
                    resolved_today.append(r)
    else:
        # CALENDAR 模式：使用 tz_offset_hours 相对 UTC 的日历
        offset = tz_offset_hours
        today_date = date_str_with_offset(now_ts, offset)

        for r in copy_list:
            if r.get("incident_status") == "RESOLVED":
                base_ts = r.get("status_updated_at") or r.get("created_at", 0.0)
                if date_str_with_offset(base_ts, offset) == today_date:
                    resolved_today.append(r)

    # 今日 bucket = unresolved + resolved_today
    today_bucket = list(unresolved) + resolved_today
    total = len(today_bucket)
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in today_bucket:
        t = r.get("incident_type") or ""
        by_type[t] = by_type.get(t, 0) + 1
        s = r.get("incident_status") or ""
        by_status[s] = by_status.get(s, 0) + 1

    # 严重事件：仅统计未解决中的严重事件
    severe = sum(1 for r in unresolved if r.get("incident_status") in severe_incident_statuses)
    resolved = len(resolved_today)
    severe_items = [
        {
            "incident_id": r.get("incident_id"),
            "incident_type": r.get("incident_type"),
            "incident_status": r.get("incident_status"),
            "charger_id": r.get("charger_id"),
            "segment_id": r.get("segment_id"),
        }
        for r in unresolved
        if r.get("incident_status") in severe_incident_statuses
    ]

    # 管理员 stale 提醒：unresolved 中 base_ts 超过阈值的数量
    threshold_sec = incident_stale_minutes * 60
    stale_unresolved = 0
    for r in unresolved:
        base_ts = r.get("status_updated_at") or r.get("created_at", 0.0)
        if (now_ts - base_ts) > threshold_sec:
            stale_unresolved += 1

    return {
        "today_date": today_date,
        "total": total,
        "severe": severe,
        "resolved": resolved,
        "unresolved": len(unresolved),
        "by_type": by_type,
        "by_status": by_status,
        "severe_items": severe_items,
        "stale_unresolved": stale_unresolved,
        "day_mode": day_mode,
        "demo_day_seconds": demo_day_seconds,
        "demo_day_index": demo_day_index,
        "tz_offset_hours": tz_offset_hours,
    }
