from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request


def _extract_openai_text(resp_obj: dict) -> str:
    try:
        choices = resp_obj.get("choices") or []
        first = choices[0] if choices else {}
        msg = first.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts).strip()
    except Exception:
        pass
    return json.dumps(resp_obj, ensure_ascii=False)


def _call_joy_brain(image_png_bytes: bytes, prompt: str) -> str:
    base_url = (os.getenv("JOY_BRAIN_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("JOY_BRAIN_KEY") or "").strip()
    model = (os.getenv("JOY_BRAIN_MODEL") or "gemini-3-flash-preview-all").strip()
    timeout_s = int((os.getenv("JOY_BRAIN_TIMEOUT_SECONDS") or "20").strip() or "20")
    if not base_url or not api_key:
        raise RuntimeError("JOY_BRAIN relay not configured")

    endpoint = base_url + "/v1/chat/completions"
    png_b64 = base64.b64encode(image_png_bytes).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png_b64}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(body) if body.strip() else {}
    return _extract_openai_text(obj)


def gemini_vision_audit(image_png_bytes: bytes, prompt: str) -> str:
    """
    Provider entry used by vision_audit_report_logic.
    Priority:
    1) JOY_BRAIN relay (OpenAI-compatible chat completions)
    2) Official Gemini SDK path (if available)
    """
    # Prefer JOY_BRAIN relay when configured.
    if (os.getenv("JOY_BRAIN_BASE_URL") or "").strip() and (os.getenv("JOY_BRAIN_KEY") or "").strip():
        return _call_joy_brain(image_png_bytes, prompt)

    # Fallback to official Gemini when key exists.
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if api_key:
        try:
            # Lazy import to keep optional dependency behavior.
            from google import genai  # type: ignore

            model = (os.getenv("JOYGATE_GEMINI_MODEL") or "gemini-3.0-flash").strip()
            client = genai.Client(api_key=api_key)
            result = client.models.generate_content(
                model=model,
                contents=[
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": image_png_bytes}},
                ],
            )
            text = getattr(result, "text", None)
            if isinstance(text, str) and text.strip():
                return text
            return json.dumps({"result": str(result)}, ensure_ascii=False)
        except Exception as e:  # pragma: no cover
            return "provider error: " + str(e)

    raise RuntimeError("No AI provider configured: set JOY_BRAIN_* or GEMINI_API_KEY")
