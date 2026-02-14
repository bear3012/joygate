#!/usr/bin/env python3
"""Visual inspection script: Judge Demo A->B->C->D + manual controls test.
Captures screenshots at key moments for judge review.
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Install: pip install playwright && playwright install chromium")
    exit(1)


URL = "http://127.0.0.1:8000/ui?god=1"
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)


async def main():
    findings = {
        "pass": True,
        "issues": [],
        "suggestions": [],
        "screenshots": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        page = await browser.new_page()
        page.set_default_timeout(20000)

        try:
            print("Opening page...")
            await page.goto(URL, wait_until="networkidle")
            await asyncio.sleep(2)
            
            # Screenshot 1: Initial state
            ts1 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts1}_01_initial.png")
            findings["screenshots"].append(f"{ts1}_01_initial.png: Initial state")
            print(f"[{ts1}] Screenshot: Initial state")

            # Check for 20x20 grid and bots
            canvas = page.locator("#canv")
            if await canvas.count() == 0:
                findings["issues"].append("[CRITICAL] Canvas not found")
                findings["pass"] = False

            # Open Controls
            print("Opening Controls drawer...")
            fab = page.locator("#godFab")
            if await fab.count() > 0:
                await fab.click()
                await asyncio.sleep(1)
            else:
                findings["issues"].append("[CRITICAL] Controls button not found")
                findings["pass"] = False

            # Screenshot 2: Controls open
            ts2 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts2}_02_controls_open.png")
            findings["screenshots"].append(f"{ts2}_02_controls_open.png: Controls drawer")
            print(f"[{ts2}] Screenshot: Controls open")

            # Click Run Judge Demo
            print("Clicking Run Judge Demo...")
            btn = page.locator("#btnJudgeDemo")
            if await btn.count() == 0:
                findings["issues"].append("[CRITICAL] Run Judge Demo button not found")
                findings["pass"] = False
            else:
                await btn.click()
                await asyncio.sleep(1)

            # Screenshot 3: Demo started
            ts3 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts3}_03_demo_started.png")
            findings["screenshots"].append(f"{ts3}_03_demo_started.png: Demo just started")
            print(f"[{ts3}] Screenshot: Demo started")

            # Observe Step A (0-3s)
            print("Observing Step A...")
            await asyncio.sleep(3)
            ts4 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts4}_04_step_A_voting.png")
            findings["screenshots"].append(f"{ts4}_04_step_A_voting.png: Step A voting")
            
            # Check for NO_WIT
            content = await page.content()
            if "NO_WIT" in content:
                findings["issues"].append("[HIGH] NO_WIT prompt visible in Step A")
                findings["pass"] = False
            if "No nearby witnesses" in content:
                findings["issues"].append("[HIGH] No nearby witnesses toast in Step A")
                findings["pass"] = False

            # Observe Step B (3-8s)
            print("Observing Step B...")
            await asyncio.sleep(5)
            ts5 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts5}_05_step_B_charging.png")
            findings["screenshots"].append(f"{ts5}_05_step_B_charging.png: Step B charging dispatch")

            # Observe Step C (8-15s)
            print("Observing Step C AI audit...")
            await asyncio.sleep(7)
            ts6 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts6}_06_step_C_ai_audit.png")
            findings["screenshots"].append(f"{ts6}_06_step_C_ai_audit.png: Step C AI audit")

            # Check if AI audit reason visible
            narrative = page.locator("#explainPanel")
            if await narrative.count() > 0:
                ntext = await narrative.text_content()
                if not (ntext and ("AI audit" in ntext or "vision" in ntext.lower() or "audit" in ntext.lower())):
                    findings["issues"].append("[MEDIUM] AI audit step not visible in narrative")
                    findings["suggestions"].append("Add explicit narrative entry for Step C AI audit")

            # Observe Step D (15-20s)
            print("Observing Step D Human fix...")
            await asyncio.sleep(5)
            ts7 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts7}_07_step_D_human_fix.png")
            findings["screenshots"].append(f"{ts7}_07_step_D_human_fix.png: Step D human fix")

            # Check for CLEARED/RESOLVED
            content_final = await page.content()
            if not ("CLEARED" in content_final or "RESOLVED" in content_final or "cleared" in content_final):
                findings["issues"].append("[MEDIUM] CLEARED/RESOLVED mark not found after Step D")
                findings["suggestions"].append("Ensure Step D work_order succeeds and shows CLEARED mark")

            # Wait for demo completion
            print("Waiting for demo to complete...")
            await asyncio.sleep(5)
            ts8 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts8}_08_demo_complete.png")
            findings["screenshots"].append(f"{ts8}_08_demo_complete.png: Demo complete")

            # Test manual controls
            print("\nTesting manual controls...")
            
            # Test A: Obstacle
            await page.locator("#btnObstacle").click()
            await asyncio.sleep(2)
            ts9 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts9}_09_manual_obstacle.png")
            findings["screenshots"].append(f"{ts9}_09_manual_obstacle.png: Manual Obstacle test")
            print(f"[{ts9}] Manual Obstacle clicked")

            # Test B: Charging
            await page.locator("#btnCharging").click()
            await asyncio.sleep(2)
            ts10 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts10}_10_manual_charging.png")
            findings["screenshots"].append(f"{ts10}_10_manual_charging.png: Manual Charging test")
            print(f"[{ts10}] Manual Charging clicked")

            # Test C: Vision
            await page.locator("#btnVision").click()
            await asyncio.sleep(2)
            ts11 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts11}_11_manual_vision.png")
            findings["screenshots"].append(f"{ts11}_11_manual_vision.png: Manual Vision test")
            print(f"[{ts11}] Manual Vision clicked")

            # Test D: Work Order need to select a cell first
            # Click on canvas to select a cell
            canvas_elem = page.locator("#canv")
            box = await canvas_elem.bounding_box()
            if box:
                # Click at center of canvas roughly cell 10,10
                await page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
                await asyncio.sleep(1)
                await page.locator("#btnWorkOrder").click()
                await asyncio.sleep(2)
                ts12 = datetime.now().strftime("%H%M%S")
                await page.screenshot(path=SCREENSHOT_DIR / f"{ts12}_12_manual_workorder.png")
                findings["screenshots"].append(f"{ts12}_12_manual_workorder.png: Manual WorkOrder test")
                print(f"[{ts12}] Manual WorkOrder clicked")

            # Final screenshot
            await asyncio.sleep(2)
            ts13 = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=SCREENSHOT_DIR / f"{ts13}_13_final_state.png")
            findings["screenshots"].append(f"{ts13}_13_final_state.png: Final state after all tests")

            print("\nVisual inspection complete. Keeping browser open for 10s...")
            await asyncio.sleep(10)

        except Exception as e:
            findings["issues"].append(f"[CRITICAL] Exception: {e}")
            findings["pass"] = False
        finally:
            await browser.close()

    return findings


def report(findings):
    print("\n" + "=" * 70)
    print("视觉验收报告 Visual Inspection Report")
    print("=" * 70)
    print(f"时间: {datetime.now().isoformat()}")
    print()

    # Verdict
    verdict = "PASS" if findings["pass"] else "FAIL"
    print(f"1 结论: {verdict}")
    print()

    # Issues
    print("2 发现按严重程度:")
    if not findings["issues"]:
        print("   无明显问题")
    else:
        for issue in findings["issues"]:
            print(f"   {issue}")
    print()

    # Suggestions
    print("3 建议最多3条:")
    if not findings["suggestions"]:
        print("   暂无建议")
    else:
        for i, sug in enumerate(findings["suggestions"][:3], 1):
            print(f"   {i}. {sug}")
    print()

    # Screenshots
    print("4 关键截图说明:")
    for ss in findings["screenshots"]:
        print(f"   - {ss}")
    print()
    print(f"所有截图保存在: {SCREENSHOT_DIR.absolute()}")
    print("=" * 70)


if __name__ == "__main__":
    findings = asyncio.run(main())
    report(findings)
