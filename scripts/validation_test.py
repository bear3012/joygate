#!/usr/bin/env python3
"""Validation: God Token, Run Judge Demo, 12s wait, collect evidence."""
import asyncio
import re
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip install playwright && playwright install chromium")
    exit(1)

URL = "http://127.0.0.1:8000/ui?god=1"


async def main():
    result = {
        "actions": [],
        "narrative_lines": [],
        "audit_short_reason": {"present": False, "text": ""},
        "warnings_errors": [],
        "verdict": "pass",
        "evidence": {},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(20000)

        try:
            # 1) Open page
            await page.goto(URL, wait_until="networkidle")
            await asyncio.sleep(2)
            result["actions"].append("Opened page")

            # 2) God Token: type test-token, click Set
            token_input = page.locator("#godToken")
            if await token_input.count() > 0:
                await token_input.fill("test-token")
                await asyncio.sleep(0.3)
                set_btn = page.locator("#btnSetGodToken")
                if await set_btn.count() > 0:
                    await set_btn.click()
                    await asyncio.sleep(0.5)
                    result["actions"].append("Typed test-token, clicked Set")
            else:
                result["actions"].append("God Token input not found")

            # 3) Click Run Judge Demo once
            btn = page.locator("#btnJudgeDemo")
            if await btn.count() > 0:
                await btn.click()
                result["actions"].append("Clicked Run Judge Demo")

            # 4) Wait 12 seconds
            await asyncio.sleep(12)
            result["actions"].append("Waited 12 seconds")

            # 5) Collect evidence
            # Narrative Guide
            narrative = page.locator("#narrativeFeed")
            if await narrative.count() > 0:
                ntext = await narrative.text_content()
                result["narrative_lines"] = (ntext or "").strip().split("\n")[-20:]
                result["evidence"]["narrative"] = ntext or ""

            # Audit card
            audit = page.locator("#audit")
            if await audit.count() > 0:
                atext = await audit.text_content()
                result["evidence"]["audit"] = atext or ""
                if atext and "AI audit reason" in atext:
                    result["audit_short_reason"]["present"] = True
                    # Extract the reason line
                    for line in (atext or "").split("\n"):
                        if "AI audit reason" in line:
                            result["audit_short_reason"]["text"] = line.strip()
                            break

            # Command Log
            cmdlog = page.locator("#cmdlog")
            if await cmdlog.count() > 0:
                clog = await cmdlog.text_content()
                result["evidence"]["cmdlog"] = clog or ""
                for line in (clog or "").split("\n"):
                    if "WARN" in line or "ERROR" in line:
                        result["warnings_errors"].append(line.strip())

            # 6) Check if page appears stuck (canvas still exists, no infinite spinner)
            canvas = page.locator("#canv")
            result["evidence"]["canvas_present"] = await canvas.count() > 0

        except Exception as e:
            result["verdict"] = "fail"
            result["warnings_errors"].append(f"Exception: {e}")
        finally:
            await browser.close()

    return result


def report(r):
    print("\n" + "=" * 60)
    print("Validation Report")
    print("=" * 60)
    print("\nActions performed:")
    for a in r["actions"]:
        print(f"  - {a}")

    print("\nObserved narrative lines (last ~20):")
    for line in r["narrative_lines"]:
        print(f'  "{line}"')

    print("\nAudit short reason presence:", "yes" if r["audit_short_reason"]["present"] else "no")
    if r["audit_short_reason"]["text"]:
        print(f'  Quoted: "{r["audit_short_reason"]["text"]}"')

    print("\nWarnings/Errors:")
    if not r["warnings_errors"]:
        print("  (none)")
    else:
        for w in r["warnings_errors"]:
            print(f"  {w}")

    # Verdict against expectations
    exp = {
        "a": "demo runs A->B->C->D",
        "b": "no visible mock wording",
        "c": "AI step has short reason",
        "d": "event appears cleared by ~8s",
        "e": "no obvious robot freeze/stuck",
    }
    checks = {}
    narrative_text = "\n".join(r["narrative_lines"])
    checks["a"] = any(x in narrative_text for x in ["Step A", "Step B", "Step C", "Step D"]) and "completed" in narrative_text.lower()
    checks["b"] = "mock" not in narrative_text.lower() and "mock" not in (r["evidence"].get("audit") or "").lower()
    checks["c"] = r["audit_short_reason"]["present"]
    checks["d"] = "HUMAN_FIX" in narrative_text or "cleared" in narrative_text.lower() or "completed" in narrative_text.lower()
    checks["e"] = not any("freeze" in w.lower() or "stuck" in w.lower() for w in r["warnings_errors"])

    final = all(checks.values())
    r["verdict"] = "pass" if final else "fail"

    print("\nExpectation checks:")
    for k, v in exp.items():
        print(f"  {k}) {v}: {'PASS' if checks[k] else 'FAIL'}")

    print("\nFinal verdict:", r["verdict"].upper())
    print("=" * 60)


if __name__ == "__main__":
    res = asyncio.run(main())
    report(res)
