#!/usr/bin/env python3
"""E2E stress test: 3x Judge Demo reruns + 30s real obstacle run."""
import asyncio
import json
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip install playwright && playwright install chromium")
    exit(1)

URL = "http://127.0.0.1:8000/ui?god=1"


def check_criteria(narrative, audit, cmdlog):
    """Returns dict of pass/fail for a-e."""
    n = narrative or ""
    a = audit or ""
    c = cmdlog or ""
    return {
        "a": all(x in n for x in ["Step A", "Step B", "Step C", "Step D"]) and "completed" in n.lower(),
        "b": "AI audit reason" in a,
        "c": "8s" in n or "cleared" in n.lower() or "auto-cleared" in n.lower(),
        "d": "mock" not in n.lower() and "mock" not in a.lower(),
        "e": not any(x in c.lower() for x in ["freeze", "stuck", "fatal"]),
    }


async def main():
    result = {
        "phase_a": {"run1": {}, "run2": {}, "run3": {}},
        "phase_b": {"fallback_5s": False, "event_cleared_8s": False, "robots_recovered": True, "warnings_errors": []},
        "quoted_lines": [],
        "residual_risks": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(25000)

        try:
            await page.goto(URL, wait_until="networkidle")
            await asyncio.sleep(2)

            # Set God token
            await page.locator("#godToken").fill("test-token")
            await asyncio.sleep(0.2)
            await page.locator("#btnSetGodToken").click()
            await asyncio.sleep(0.5)

            # Phase A: 3 consecutive Judge Demo runs
            for run_num in [1, 2, 3]:
                run_key = f"run{run_num}"
                # Close evidence modal if open (blocks button on run 2+)
                close_btn = page.locator("#btnCloseEvidence")
                if await close_btn.count() > 0 and await close_btn.is_visible():
                    await close_btn.click()
                    await asyncio.sleep(0.5)
                await page.locator("#btnJudgeDemo").click()
                await asyncio.sleep(12)

                narrative = (await page.locator("#narrativeFeed").text_content()) or ""
                audit = (await page.locator("#audit").text_content()) or ""
                cmdlog = (await page.locator("#cmdlog").text_content()) or ""

                criteria = check_criteria(narrative, audit, cmdlog)
                result["phase_a"][run_key] = {
                    "a": criteria["a"],
                    "b": criteria["b"],
                    "c": criteria["c"],
                    "d": criteria["d"],
                    "e": criteria["e"],
                    "snippet": narrative[-500:] if not all(criteria.values()) else None,
                }
                if run_num == 1:
                    result["quoted_lines"].extend(narrative.strip().split("\n")[-15:])

            # Phase B: A Simulate Obstacle, observe 30s
            # Close evidence modal if still open
            close_btn = page.locator("#btnCloseEvidence")
            if await close_btn.count() > 0 and await close_btn.is_visible():
                await close_btn.click()
                await asyncio.sleep(0.5)
            # Select a road cell first (center-ish: 10,10 is on main cross)
            canvas = page.locator("#canv")
            box = await canvas.bounding_box()
            if box:
                await page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.52)
                await asyncio.sleep(0.5)

            await page.locator("#btnObstacle").click()
            await asyncio.sleep(30)

            narrative_b = (await page.locator("#narrativeFeed").text_content()) or ""
            audit_b = (await page.locator("#audit").text_content()) or ""
            cmdlog_b = (await page.locator("#cmdlog").text_content()) or ""

            # Phase B checks
            result["phase_b"]["fallback_5s"] = "5s" in narrative_b or "fallback" in narrative_b.lower() or "timeout" in narrative_b.lower()
            result["phase_b"]["event_cleared_8s"] = "8s" in narrative_b or "cleared" in narrative_b.lower() or "auto-cleared" in narrative_b.lower()
            result["phase_b"]["warnings_errors"] = [l.strip() for l in (cmdlog_b or "").split("\n") if "WARN" in l or "ERROR" in l]

            if result["phase_b"]["warnings_errors"]:
                result["phase_b"]["robots_recovered"] = not any("stuck" in w.lower() or "freeze" in w.lower() for w in result["phase_b"]["warnings_errors"])

            for line in narrative_b.strip().split("\n"):
                if line.strip():
                    result["quoted_lines"].append(f"[Phase B] {line.strip()}")

        except Exception as e:
            result["residual_risks"].append(f"Exception: {e}")
        finally:
            await browser.close()

    return result


def report(r):
    # Overall verdict
    phase_a_ok = all(
        all(r["phase_a"][k].get(x, False) for x in ["a", "b", "c", "d", "e"])
        for k in ["run1", "run2", "run3"]
    )
    phase_b_ok = (
        r["phase_b"]["fallback_5s"] or r["phase_b"]["event_cleared_8s"]
    ) and r["phase_b"]["robots_recovered"]
    verdict = "PASS" if phase_a_ok and phase_b_ok else "FAIL"

    print("\n" + "=" * 70)
    print("E2E STRESS TEST REPORT")
    print("=" * 70)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"\nOverall verdict: {verdict}")
    print("\n--- Phase A: 3 consecutive Judge Demo reruns ---")
    print("| Run  | a) A/B/C/D+done | b) AI reason | c) 8s clear | d) no mock | e) no stuck |")
    print("|------|-----------------|-------------|-------------|------------|--------------|")
    for k in ["run1", "run2", "run3"]:
        row = r["phase_a"].get(k, {})
        a = "PASS" if row.get("a") else "FAIL"
        b = "PASS" if row.get("b") else "FAIL"
        c = "PASS" if row.get("c") else "FAIL"
        d = "PASS" if row.get("d") else "FAIL"
        e = "PASS" if row.get("e") else "FAIL"
        print(f"| {k:4} | {a:15} | {b:11} | {c:11} | {d:10} | {e:12} |")
        if row.get("snippet"):
            print(f"      Snippet: {row['snippet'][:120]}...")

    print("\n--- Phase B: Real 30s obstacle run ---")
    pb = r["phase_b"]
    print(f"  a) Fallback handling ~5s: {'yes' if pb['fallback_5s'] else 'no'}")
    print(f"  b) Event cleared ~8s: {'yes' if pb['event_cleared_8s'] else 'no'}")
    print(f"  c) Robots recovered, no long stuck: {'yes' if pb['robots_recovered'] else 'no'}")
    print(f"  d) Warnings/errors: {pb['warnings_errors'] if pb['warnings_errors'] else '(none)'}")

    print("\n--- Key quoted narrative/audit lines ---")
    for line in r["quoted_lines"][:25]:
        print(f'  "{line[:100]}"')

    if r["residual_risks"]:
        print("\n--- Residual risks ---")
        for risk in r["residual_risks"]:
            print(f"  - {risk}")
    print("=" * 70)


if __name__ == "__main__":
    res = asyncio.run(main())
    report(res)
