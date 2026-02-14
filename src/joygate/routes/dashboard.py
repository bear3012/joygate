from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/demo")
def demo_redirect():
    """演示入口，重定向到 dashboard"""
    return RedirectResponse(url="/dashboard/incidents_daily", status_code=302)


@router.get("/dashboard/incidents_daily", response_class=HTMLResponse)
def dashboard_incidents_daily(request: Request):
    """今日 incidents 汇总 HTML；统计基于 store.incidents_daily_report，不做对外 schema 变更。
    此页会被 /ui 用 iframe 嵌入（同域可读 sessionStorage），所有动态内容必须 html.escape，禁止 innerHTML 拼未转义字符串。"""
    store = request.state.store
    report = store.incidents_daily_report()
    today = html.escape(report["today_date"])
    total = html.escape(str(report["total"]))
    severe = html.escape(str(report["severe"]))
    resolved = html.escape(str(report["resolved"]))
    unresolved = html.escape(str(report["unresolved"]))
    stale_unresolved = html.escape(str(report.get("stale_unresolved", 0)))
    day_mode = report.get("day_mode", "DEMO")
    demo_day_seconds = report.get("demo_day_seconds")
    demo_day_index = report.get("demo_day_index")
    tz_offset_hours = report.get("tz_offset_hours")
    rows_type = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in sorted(report["by_type"].items())
    )
    rows_status = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in sorted(report["by_status"].items())
    )
    rows_severe = "".join(
        f"<tr><td>{html.escape(str(item.get('incident_id')))}</td><td>{html.escape(str(item.get('incident_type')))}</td>"
        f"<td>{html.escape(str(item.get('incident_status')))}</td><td>{html.escape(str(item.get('charger_id') or ''))}</td>"
        f"<td>{html.escape(str(item.get('segment_id') or ''))}</td></tr>"
        for item in report["severe_items"]
    )
    # 生成模式说明块（带 data-testid 锚点）
    if day_mode == "DEMO":
        mode_label = html.escape(day_mode)
        seconds_label = html.escape(str(demo_day_seconds or ""))
        index_label = html.escape(str(demo_day_index or ""))
        day_meta = (
            f'<p data-testid="dashboard-day-meta">'
            f'Mode=<span data-testid="dashboard-day-mode">{mode_label}</span>, '
            f'day_seconds=<span data-testid="dashboard-demo-day-seconds">{seconds_label}</span>, '
            f'day_index=<span data-testid="dashboard-demo-day-index">{index_label}</span>'
            f'</p>'
        )
    else:
        mode_label = html.escape(day_mode)
        offset_label = html.escape(str(tz_offset_hours or ""))
        day_meta = (
            f'<p data-testid="dashboard-day-meta">'
            f'Mode=<span data-testid="dashboard-day-mode">{mode_label}</span>, '
            f'tz_offset_hours=<span data-testid="dashboard-tz-offset-hours">{offset_label}</span>'
            f'</p>'
        )
    
    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Incidents Daily - {today}</title></head>
<body>
<h1>Incidents Daily ({today})</h1>
{day_meta}
<table border="1">
<caption>Summary</caption>
<tr><td>Total</td><td><span data-testid="summary-total">{total}</span></td></tr>
<tr><td>Severe</td><td><span data-testid="summary-severe">{severe}</span></td></tr>
<tr><td>Resolved</td><td><span data-testid="summary-resolved">{resolved}</span></td></tr>
<tr><td>Unresolved</td><td><span data-testid="summary-unresolved">{unresolved}</span></td></tr>
<tr><td>Stale Unresolved</td><td><span data-testid="summary-stale-unresolved">{stale_unresolved}</span></td></tr>
</table>
<table border="1">
<caption>By Type</caption>
<tr><th>incident_type</th><th>count</th></tr>
{rows_type}
</table>
<table border="1">
<caption>By Status</caption>
<tr><th>incident_status</th><th>count</th></tr>
{rows_status}
</table>
<table border="1">
<caption>Severe Items</caption>
<tr><th>incident_id</th><th>incident_type</th><th>incident_status</th><th>charger_id</th><th>segment_id</th></tr>
{rows_severe}
</table>
</body></html>"""
    return body
