"""One-off helper to capture the README screenshot. Needs playwright."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).with_name("dashboard.png")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1.5)
    page.goto("http://localhost:8501", wait_until="domcontentloaded")
    page.wait_for_selector("text=Explore a location", timeout=60_000)
    page.wait_for_timeout(8_000)  # let the WebGL map and plots finish painting
    page.screenshot(path=str(OUT), full_page=False)
    browser.close()

print(f"saved {OUT}")
