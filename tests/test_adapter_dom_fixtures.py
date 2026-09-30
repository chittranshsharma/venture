"""
tests/test_adapter_dom_fixtures.py — DOM fixture verification for ATS adapters:
1. Synthetic fixtures (*_synthetic.html): baseline regression checks on known adapter selectors.
2. Real fixtures (*_real.html): captured live pages from boards.greenhouse.io, jobs.lever.co, jobs.ashbyhq.com.
3. Submission safety: asserts submit button is NEVER clicked in dry-run mode.
"""

import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from playwright.async_api import async_playwright
from automation.specialists.greenhouse_adapter import GreenhouseAdapter
from automation.specialists.lever_adapter import LeverAdapter
from automation.specialists.ashby_adapter import AshbyAdapter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SAMPLE_PROFILE = {
    "first_name": "Chittransh",
    "last_name": "Sharma",
    "full_name": "Chittransh Sharma",
    "email": "chittransh@example.com",
    "phone": "+91 9876543210",
    "location": "Bengaluru, India",
    "company": "Tech Corp",
    "linkedin": "https://linkedin.com/in/chittransh",
    "github": "https://github.com/chittransh",
    "portfolio": "https://chittransh.dev",
    "resume_path": "",
}

class MockPackage:
    def __init__(self, profile):
        self.form_answers = profile.copy()
        self.resume_path = ""
        self.cover_letter_text = "Experienced full stack engineer."


def test_greenhouse_dom_fixture():
    async def _run():
        fixture_path = FIXTURES_DIR / "greenhouse_real.html"
        if not fixture_path.exists():
            fixture_path = FIXTURES_DIR / "greenhouse_synthetic.html"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
        html_content = fixture_path.read_text(encoding="utf-8")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content)

            adapter = GreenhouseAdapter()
            assert adapter.can_handle("https://boards.greenhouse.io/job/123", html_content)

            # Inspect
            info = await adapter.inspect(page)
            assert info["has_first_name"]
            assert info["has_last_name"]
            assert info["has_email"]
            assert info["has_submit"]

            # Fill
            pkg = MockPackage(SAMPLE_PROFILE)
            with patch("core.db_manager.set_checkpoint"), patch("core.db_manager.log_message"):
                filled = await adapter.fill(page, pkg, SAMPLE_PROFILE)
                assert filled

                # Verify DOM field values
                fn_val = await page.locator("input#first_name").input_value()
                ln_val = await page.locator("input#last_name").input_value()
                em_val = await page.locator("input#email").input_value()
                ph_val = await page.locator("input#phone").input_value()

                assert fn_val == "Chittransh"
                assert ln_val == "Sharma"
                assert em_val == "chittransh@example.com"
                assert ph_val == "+91 9876543210"

                # Validate
                v_res = await adapter.validate(page)
                assert v_res["valid"]
                assert len(v_res["missing_required"]) == 0

                # Dry Run Submit: button must NOT be clicked
                submit_btn = page.locator("button#submit_app")
                with patch.object(submit_btn, "click", MagicMock()) as mock_click:
                    res = await adapter.submit(page, dry_run=True)
                    assert res is True
                    mock_click.assert_not_called()

            await browser.close()

    asyncio.run(_run())


def test_lever_dom_fixture():
    async def _run():
        fixture_path = FIXTURES_DIR / "lever_real.html"
        if not fixture_path.exists():
            fixture_path = FIXTURES_DIR / "lever_synthetic.html"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
        html_content = fixture_path.read_text(encoding="utf-8")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content)

            adapter = LeverAdapter()
            assert adapter.can_handle("https://jobs.lever.co/company/abc", html_content)

            # Inspect
            info = await adapter.inspect(page)
            assert info["has_name"]
            assert info["has_email"]
            assert info["has_submit"]

            # Fill
            pkg = MockPackage(SAMPLE_PROFILE)
            with patch("core.db_manager.set_checkpoint"), patch("core.db_manager.log_message"):
                filled = await adapter.fill(page, pkg, SAMPLE_PROFILE)
                assert filled

                name_val = await page.locator("input[name='name']").input_value()
                em_val = await page.locator("input[name='email']").input_value()
                ph_val = await page.locator("input[name='phone']").input_value()

                assert name_val == "Chittransh Sharma"
                assert em_val == "chittransh@example.com"
                assert ph_val == "+91 9876543210"

                # Validate
                v_res = await adapter.validate(page)
                assert v_res["valid"]

                # Dry run submit
                res = await adapter.submit(page, dry_run=True)
                assert res is True

            await browser.close()

    asyncio.run(_run())


def test_ashby_dom_fixture():
    async def _run():
        fixture_path = FIXTURES_DIR / "ashby_real.html"
        if not fixture_path.exists():
            fixture_path = FIXTURES_DIR / "ashby_synthetic.html"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
        html_content = fixture_path.read_text(encoding="utf-8")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content)

            adapter = AshbyAdapter()
            assert adapter.can_handle("https://jobs.ashbyhq.com/company/abc", html_content)

            # Inspect
            info = await adapter.inspect(page)
            assert info["has_name"]
            assert info["has_email"]
            assert info["has_submit"]

            # Fill
            pkg = MockPackage(SAMPLE_PROFILE)
            with patch("core.db_manager.set_checkpoint"), patch("core.db_manager.log_message"):
                filled = await adapter.fill(page, pkg, SAMPLE_PROFILE)
                assert filled

                name_val = await page.locator("input[name='name']").input_value()
                em_val = await page.locator("input[name='email']").input_value()
                ph_val = await page.locator("input[name='phoneNumber']").input_value()

                assert name_val == "Chittransh Sharma"
                assert em_val == "chittransh@example.com"
                assert ph_val == "+91 9876543210"

                # Validate
                v_res = await adapter.validate(page)
                assert v_res["valid"]

                # Dry run submit
                res = await adapter.submit(page, dry_run=True)
                assert res is True

            await browser.close()

    asyncio.run(_run())
