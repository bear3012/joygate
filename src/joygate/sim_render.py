"""
M12A-1：Sim 渲染 — 根据 render_snapshot 在内存绘制 PNG（网格、charger、blocked cell、机器人轨迹）。
不写文件，只返回 bytes。
"""
from __future__ import annotations

import io
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    Image = None
    ImageDraw = None
    _PIL_ERROR = e


def render_sim_snapshot_png(render_snapshot: dict[str, Any]) -> bytes:
    """
    用 PIL 在内存绘制 PNG：网格、charger 点、blocked cell、机器人轨迹。
    render_snapshot 至少含：incident_id, charger_id, chargers_layout, blocked_cell, robot_tracks, created_at。
    返回 PNG bytes，不落盘。
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError(f"PIL (Pillow) required for sim render: {_PIL_ERROR}") from _PIL_ERROR

    w, h = 400, 400
    img = Image.new("RGB", (w, h), color=(248, 248, 252))
    draw = ImageDraw.Draw(img)

    # 简单网格（例如 4x4）
    grid_n = 4
    cell_w = w // grid_n
    cell_h = h // grid_n
    for i in range(grid_n + 1):
        draw.line([(i * cell_w, 0), (i * cell_w, h)], fill=(200, 200, 210), width=1)
        draw.line([(0, i * cell_h), (w, i * cell_h)], fill=(200, 200, 210), width=1)

    # chargers_layout: list of charger_id 或 dict charger_id -> 位置；这里按顺序画点
    chargers_layout = render_snapshot.get("chargers_layout") or []
    if isinstance(chargers_layout, dict):
        chargers_layout = list(chargers_layout.keys())
    for idx, cid in enumerate(chargers_layout[:16]):
        row, col = idx // grid_n, idx % grid_n
        cx = col * cell_w + cell_w // 2
        cy = row * cell_h + cell_h // 2
        r = 6
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(80, 180, 80), outline=(40, 120, 40))

    # blocked_cell: segment_id 如 cell_1_2 -> 填该格
    blocked_cell = render_snapshot.get("blocked_cell")
    if isinstance(blocked_cell, str) and blocked_cell.startswith("cell_") and "_" in blocked_cell[5:]:
        parts = blocked_cell[5:].split("_", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            col, row = int(parts[0]), int(parts[1])
            if 0 <= row < grid_n and 0 <= col < grid_n:
                x1, y1 = col * cell_w, row * cell_h
                draw.rectangle([x1, y1, x1 + cell_w - 1, y1 + cell_h - 1], fill=(255, 200, 200), outline=(200, 100, 100))

    # robot_tracks: dict joykey -> list[segment_id] 或 list of segment_id；画线段/点
    robot_tracks = render_snapshot.get("robot_tracks") or {}
    if isinstance(robot_tracks, list):
        robot_tracks = {"_": robot_tracks}
    points: list[tuple[int, int]] = []
    for track_list in robot_tracks.values() if isinstance(robot_tracks, dict) else []:
        if not isinstance(track_list, list):
            continue
        for seg in track_list[:20]:
            if not isinstance(seg, str) or not seg.startswith("cell_") or "_" not in seg[5:]:
                continue
            parts = seg[5:].split("_", 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            col, row = int(parts[0]), int(parts[1])
            if 0 <= row < grid_n and 0 <= col < grid_n:
                points.append((col * cell_w + cell_w // 2, row * cell_h + cell_h // 2))
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=(100, 100, 255), width=2)
    for (px, py) in points:
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(80, 80, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
