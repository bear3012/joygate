#!/usr/bin/env python3
"""Browser acceptance test for JoyGate UI demo."""
import time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000/ui?god=1"

def main():
    evidence = []
    blockers = []
    risks = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(15000)
        
        try:
            # Step 1: Open page
            print("=== STEP 1: Opening page ===")
            page.goto(URL, wait_until="networkidle")
            time.sleep(2)
            evidence.append("Page loaded successfully")
            
            # Step 2: Set God Token
            print("=== STEP 2: Setting God Token ===")
            
            # Check if God Controls visible
            god_controls = page.locator(".god-only")
            if god_controls.count() > 0 and god_controls.first.is_visible():
                evidence.append("God Controls visible (god=1 mode active)")
            else:
                blockers.append("God Controls not visible - check ?god=1 parameter")
            
            # Fill God Token input
            token_input = page.locator("#godToken")
            if token_input.count() > 0:
                token_input.fill("123")
                evidence.append("God Token input filled with '123'")
                
                # Click Set button
                set_btn = page.locator("#btnSetGodToken")
                if set_btn.count() > 0:
                    set_btn.click()
                    time.sleep(0.5)
                    evidence.append("Set button clicked")
                    
                    # Check if buttons are enabled
                    demo_btn_disabled = page.locator("#btnJudgeDemo").is_disabled()
                    if demo_btn_disabled:
                        blockers.append("Run Judge Demo button still disabled after setting token")
                    else:
                        evidence.append("Run Judge Demo button is enabled")
                else:
                    blockers.append("Set button (#btnSetGodToken) not found")
            else:
                blockers.append("God Token input (#godToken) not found")
            
            # Step 3: Run Judge Demo
            print("=== STEP 3: Running Judge Demo ===")
            demo_btn = page.locator("#btnJudgeDemo")
            if demo_btn.count() == 0:
                blockers.append("Run Judge Demo button not found")
            else:
                demo_btn.click()
                evidence.append("Run Judge Demo clicked")
                time.sleep(2)
                
                # Monitor narrative for 40 seconds
                for i in range(8):
                    time.sleep(5)
                    narrative = page.locator("#explainPanel").text_content()
                    print(f"[t={5*(i+1)}s] Narrative last 200 chars: {narrative[-200:]}")
                    
                    # Check for step markers
                    if "Step A" in narrative or "obstacle" in narrative.lower():
                        evidence.append(f"[t={5*(i+1)}s] Step A detected in narrative")
                    if "Step B" in narrative or "charging" in narrative.lower() or "dispatch" in narrative.lower():
                        evidence.append(f"[t={5*(i+1)}s] Step B detected in narrative")
                    if "Step C" in narrative or "AI audit" in narrative or "vision" in narrative.lower():
                        evidence.append(f"[t={5*(i+1)}s] Step C detected in narrative")
                    if "Step D" in narrative or "Human fix" in narrative or "work order" in narrative.lower():
                        evidence.append(f"[t={5*(i+1)}s] Step D detected in narrative")
            
            # Step 4: Check for AI audit evidence
            print("=== STEP 4: Checking AI audit ===")
            
            # Check for modal/dialog
            modals = page.locator(".modal, [role=dialog], .drawer").all()
            print(f"Found {len(modals)} modal/dialog elements")
            
            for idx, modal in enumerate(modals):
                text = modal.text_content()
                if "Vision Audit" in text:
                    evidence.append(f"Modal {idx}: Found 'Vision Audit' in content")
                    if "mock" in text.lower():
                        blockers.append("Modal contains 'mock' keyword - not production ready")
                if "AI audit reason:" in text:
                    evidence.append(f"Modal {idx}: Found 'AI audit reason:' in content")
            
            # Check audit card
            audit_card = page.locator("#audit").text_content()
            print(f"Audit card content (first 300 chars): {audit_card[:300]}")
            
            if "AI audit reason:" in audit_card:
                evidence.append("Audit card contains 'AI audit reason:' field")
            
            # Step 5: Test manual buttons
            print("=== STEP 5: Testing manual buttons A/B/C/D ===")
            
            time.sleep(2)
            
            # A: Obstacle
            page.locator("#btnObstacle").click()
            time.sleep(2)
            narrative_a = page.locator("#explainPanel").text_content()
            if "obstacle" in narrative_a.lower() or "VOTE" in narrative_a:
                evidence.append("[A] Obstacle button: narrative updated")
            else:
                risks.append("[A] Obstacle button: no visible feedback in narrative")
            
            # B: Charging
            page.locator("#btnCharging").click()
            time.sleep(2)
            narrative_b = page.locator("#explainPanel").text_content()
            if "charging" in narrative_b.lower() or "dispatch" in narrative_b.lower():
                evidence.append("[B] Charging button: narrative updated")
            else:
                risks.append("[B] Charging button: no visible feedback in narrative")
            
            # C: Vision
            page.locator("#btnVision").click()
            time.sleep(3)
            narrative_c = page.locator("#explainPanel").text_content()
            if "vision" in narrative_c.lower() or "audit" in narrative_c.lower():
                evidence.append("[C] Vision button: narrative updated")
            else:
                risks.append("[C] Vision button: no visible feedback in narrative")
            
            # D: WorkOrder (need to select cell first)
            canvas = page.locator("#canv")
            box = canvas.bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
                time.sleep(1)
                page.locator("#btnWorkOrder").click()
                time.sleep(2)
                narrative_d = page.locator("#explainPanel").text_content()
                if "work order" in narrative_d.lower() or "Human fix" in narrative_d:
                    evidence.append("[D] WorkOrder button: narrative updated")
                else:
                    risks.append("[D] WorkOrder button: no visible feedback in narrative")
            
            print("=== Test complete, keeping browser open for 5s ===")
            time.sleep(5)
            
        except Exception as e:
            blockers.append(f"Exception: {e}")
        finally:
            browser.close()
    
    return evidence, blockers, risks


def report(evidence, blockers, risks):
    print("\n" + "=" * 70)
    print("浏览器验收报告 (Browser Acceptance Test)")
    print("=" * 70)
    
    verdict = "FAIL" if blockers else "PASS"
    print(f"\n结论: {verdict}\n")
    
    print("关键证据（逐条）:")
    if not evidence:
        print("  （无证据）")
    else:
        for i, e in enumerate(evidence, 1):
            print(f"  {i}. {e}")
    
    print("\n阻断项:")
    if not blockers:
        print("  （无阻断项）")
    else:
        for i, b in enumerate(blockers, 1):
            print(f"  {i}. {b}")
    
    print("\n残余风险（最多3条）:")
    if not risks:
        print("  （无残余风险）")
    else:
        for i, r in enumerate(risks[:3], 1):
            print(f"  {i}. {r}")
    
    print("=" * 70)


if __name__ == "__main__":
    evidence, blockers, risks = main()
    report(evidence, blockers, risks)
