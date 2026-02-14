# scripts/test_m13_registry_dispatch_explain_lock.py
from __future__ import annotations

from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    reg_path = repo_root / "docs_control_center" / "FIELD_REGISTRY.md"
    text = reg_path.read_text(encoding="utf-8", errors="strict")

    required_tokens = [
        "### /v1/ai/dispatch_explain 输入/输出",
        "M13.0 dispatch_explain_constraints: evidence_only",
        "dispatch_reason_code:",
        "dispatch_reason_codes",
        "ai_input_sha256",
    ]
    missing = [t for t in required_tokens if t not in text]
    if missing:
        print("FAIL: missing tokens in FIELD_REGISTRY.md:")
        for t in missing:
            print(f"- {t}")
        return 1

    print("PASS: M13.0 registry lock for dispatch_explain (evidence-only + enums + hash field)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
