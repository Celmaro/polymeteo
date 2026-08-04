#!/usr/bin/env python3
"""Capture dashboard screenshots for the README."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
URL = "http://127.0.0.1:5173"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 920}, device_scale_factor=2)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1200)

        page.screenshot(path=str(OUT / "01-overview-pnl.png"), full_page=False)

        page.evaluate("window.scrollTo(0, 520)")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "02-equity-funnel.png"), full_page=False)

        page.evaluate("window.scrollTo(0, 1100)")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "03-wallet-analysis.png"), full_page=False)

        page.evaluate("window.scrollTo(0, 1750)")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "04-city-fills.png"), full_page=False)

        page.screenshot(path=str(OUT / "05-full-dashboard.png"), full_page=True)
        browser.close()
    print(f"Wrote screenshots to {OUT}")


if __name__ == "__main__":
    main()
