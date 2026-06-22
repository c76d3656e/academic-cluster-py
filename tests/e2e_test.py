"""
E2E 测试：登录 → 查看项目综述页面
使用 Playwright 验证前端渲染正常
"""

import sys
import time

from playwright.sync_api import sync_playwright


def run_test():
    project_id = "4a7f3401-4c86-48bd-94ba-da3681fa8ca2"
    base_url = "http://localhost:3000"
    api_url = "http://localhost:8000"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # 1. 登录
        print("[1] Navigating to login page...")
        page.goto(f"{base_url}/login")
        page.wait_for_load_state("networkidle")
        page.screenshot(path="tests/screenshots/01_login_page.png")
        print("    Login page loaded")

        # 填写登录表单
        print("[2] Logging in as admin...")
        email_input = page.locator(
            'input[type="email"], input[name="email"], input[placeholder*="邮箱"], input[placeholder*="email"]'
        ).first
        password_input = page.locator('input[type="password"]').first

        if email_input.is_visible():
            email_input.fill("admin@cluster.local")
            password_input.fill("Admin123!")
            login_btn = page.locator(
                'button[type="submit"], button:has-text("登录"), button:has-text("Login")'
            ).first
            login_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="tests/screenshots/02_after_login.png")
            print("    Login submitted")
        else:
            print("    Could not find email input, trying direct navigation")

        # 2. 导航到项目页面
        print(f"[3] Navigating to project {project_id}...")
        page.goto(f"{base_url}/projects/{project_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        page.screenshot(path="tests/screenshots/03_project_detail.png")
        print("    Project detail page loaded")

        # 3. 检查页面内容
        print("[4] Checking page content...")
        body_text = page.inner_text("body")

        # 检查是否有综述相关内容
        checks = {
            "has_tabs": "综述" in body_text
            or "Review" in body_text
            or "概览" in body_text
            or "Overview" in body_text,
            "has_content": len(body_text) > 200,
            "no_empty_state": "尚未生成" not in body_text and "暂无" not in body_text,
        }

        for check, passed in checks.items():
            status = "PASS" if passed else "FAIL"
            print(f"    [{status}] {check}")

        # 4. 尝试点击不同标签页
        tabs = page.locator(
            '[role="tab"], .tab, button:has-text("综述"), button:has-text("Review"), button:has-text("参考"), button:has-text("Reference")'
        )
        tab_count = tabs.count()
        print(f"[5] Found {tab_count} tabs")

        for i in range(min(tab_count, 3)):
            tab = tabs.nth(i)
            if tab.is_visible():
                tab_name = tab.inner_text().strip()
                tab.click()
                time.sleep(1)
                page.screenshot(path=f"tests/screenshots/04_tab_{i}_{tab_name}.png")
                print(f"    Clicked tab: {tab_name}")

        # 5. 最终截图
        page.screenshot(path="tests/screenshots/05_final.png", full_page=True)
        print("[6] Final screenshot saved")

        # 6. 检查 API 返回的数据
        print("[7] Checking API response...")
        api_response = page.evaluate(f"""
            async () => {{
                const resp = await fetch('{api_url}/api/projects/{project_id}/review');
                if (!resp.ok) return {{ error: resp.status }};
                return await resp.json();
            }}
        """)

        if "error" in api_response:
            print(f"    API error: {api_response['error']}")
        else:
            sections = api_response.get("sections", [])
            outline = api_response.get("outline", {})
            evidence = api_response.get("evidence_cards", [])
            print(f"    Outline title: {outline.get('title', 'N/A')}")
            print(f"    Sections: {len(sections)}")
            print(f"    Evidence cards: {len(evidence)}")
            for s in sections[:3]:
                print(
                    f"      - {s.get('section_id', '?')}: {len(s.get('content', ''))} chars"
                )

        browser.close()

    # 判断测试结果
    all_passed = all(checks.values())
    print(f"\n{'=' * 50}")
    print(f"E2E Test: {'PASSED' if all_passed else 'FAILED'}")
    print(f"{'=' * 50}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    from pathlib import Path

    Path("tests/screenshots").mkdir(parents=True, exist_ok=True)
    sys.exit(run_test())
