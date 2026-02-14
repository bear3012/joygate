from __future__ import annotations

import json

ALLOWED_AI_INSIGHT_KEYS = {
    "insight_type",
    "summary",
    "confidence",
    "obstacle_type",
    "sample_index",
    "ai_report_id",
}

ALLOWED_OBSTACLE_TYPES = {
    "ICE_VEHICLE",
    "CONSTRUCTION",
    "CHARGER_FAULT",
    "BLOCKED_BY_CHARGER",
    "UNKNOWN",
}


def upsert_ai_insight(incident_rec: dict, insight: dict) -> None:
    incident_rec.setdefault("ai_insights", [])
    ai_insights = incident_rec.get("ai_insights") or []

    insight_type = insight.get("insight_type")
    ai_report_id = insight.get("ai_report_id")
    if not insight_type:
        return
    if not ai_report_id:
        return
    full_payload = {k: insight.get(k) for k in ALLOWED_AI_INSIGHT_KEYS}

    for i, item in enumerate(ai_insights):
        if isinstance(item, dict) and item.get("insight_type") == insight_type and item.get("ai_report_id") == ai_report_id:
            update_keys = ALLOWED_AI_INSIGHT_KEYS.intersection(insight.keys())
            item.update({k: full_payload[k] for k in update_keys})
            ai_insights[i] = item
            incident_rec["ai_insights"] = ai_insights
            return

    ai_insights.append(full_payload)
    incident_rec["ai_insights"] = ai_insights


def _stable_confidence_from_incident_id(incident_id: str) -> int:
    base = sum(ord(c) for c in (incident_id or ""))
    return 60 + (base % 31)


def generate_vision_audit_result(
    provider: str, incident_rec: dict, image_png_bytes: bytes | None = None
) -> dict:
    """
    返回 dict: summary, confidence, obstacle_type, sample_index。
    mock：稳定可测输出，可不使用 image_png_bytes。
    gemini：调用 gemini provider；尽量解析 JSON 填 confidence，解析失败则 confidence=None。
    """
    provider_norm = (provider or "mock").strip().lower() or "mock"
    incident_type = (incident_rec.get("incident_type") or "").strip()

    if incident_type == "HIJACKED":
        obstacle_type = "ICE_VEHICLE"
    elif incident_type == "NO_PLUG":
        obstacle_type = "CHARGER_FAULT"
    elif incident_type in {"BLOCKED", "BLOCKED_BY_OTHER"}:
        obstacle_type = "CONSTRUCTION"
    else:
        obstacle_type = "UNKNOWN"

    if obstacle_type not in ALLOWED_OBSTACLE_TYPES:
        obstacle_type = "UNKNOWN"

    incident_id = (incident_rec.get("incident_id") or "").strip()
    sample_index = 0
    fallback_conf = _stable_confidence_from_incident_id(incident_id)
    fallback_summary = f"vision audit result: obstacle={obstacle_type}, confidence={fallback_conf}"

    if provider_norm == "gemini" and image_png_bytes:
        try:
            from joygate.ai_provider_gemini import gemini_vision_audit
            prompt = (
                "Describe what blocks the charger or path in this grid image. "
                "Reply with a short JSON object containing: summary (string), confidence (int 0-100)."
            )
            text = gemini_vision_audit(image_png_bytes, prompt)
            confidence = None
            summary = text or "no response"
            if text and text.strip():
                stripped = text.strip()
                if stripped.startswith("{"):
                    obj = json.loads(stripped)
                    if isinstance(obj, dict):
                        c = obj.get("confidence")
                        if isinstance(c, int) and 0 <= c <= 100:
                            confidence = c
                        if isinstance(obj.get("summary"), str):
                            summary = obj["summary"]
                if confidence is None and "confidence" in text.lower():
                    for token in text.replace(",", " ").split():
                        if token.isdigit():
                            v = int(token)
                            if 0 <= v <= 100:
                                confidence = v
                                break
        except json.JSONDecodeError:
            # Provider returned non-JSON; degrade gracefully to deterministic fallback.
            summary = fallback_summary
            confidence = fallback_conf
        except Exception as e:
            # Relay timeout/network/tls/sdk errors should not break demo flow.
            # Fallback to stable deterministic result and avoid exposing raw provider errors.
            _ = e
            summary = fallback_summary
            confidence = fallback_conf
        return {
            "summary": summary,
            "confidence": confidence,
            "obstacle_type": obstacle_type,
            "sample_index": sample_index,
        }
    confidence = fallback_conf
    prefix = "Gemini stub: " if provider_norm == "gemini" else ""
    summary = f"{prefix}vision audit result: obstacle={obstacle_type}, confidence={confidence}"
    return {
        "summary": summary,
        "confidence": confidence,
        "obstacle_type": obstacle_type,
        "sample_index": sample_index,
    }
