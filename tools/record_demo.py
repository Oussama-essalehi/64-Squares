"""Record the README visuals: an animated tour of the web dashboard and a screenshot of the app.

The tour opens on the intro pop-up, walks through the four pages in French, switches to dark mode
and ends on the English version.

Needs Playwright with a Chromium build, and both pages served locally:

    python -m http.server 8000 --directory site
    streamlit run app/streamlit_app.py --server.headless true

Usage: ``python tools/record_demo.py [--chromium PATH]``
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "reports" / "figures"
SITE_URL, APP_URL = "http://localhost:8000/", "http://localhost:8501/"
WIDTH = 1100


def grab(page: Page) -> Image.Image:
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.3)
    shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    return shot.resize((WIDTH, round(shot.height * WIDTH / shot.width)), Image.LANCZOS)


def record_dashboard(page: Page) -> Path:
    page.goto(SITE_URL, wait_until="networkidle")
    page.wait_for_selector(".kpi .value")
    time.sleep(1.5)
    steps = [
        (None, 4200),  # intro pop-up
        (lambda: page.click("#intro [data-i18n='intro.start']"), 2600),
        (lambda: page.select_option("#f-tc", "3"), 1600),  # Blitz
        (lambda: page.select_option("#f-band", "4"), 2000),  # 2000+
        (lambda: page.click("#t-openings"), 2600),
        (lambda: page.locator("#opening-table tbody tr").nth(4).click(), 2400),
        (lambda: page.select_option("#f-side", "black"), 2400),
        (lambda: page.click("#t-elo"), 2600),
        (
            lambda: (page.select_option("#f-tc", "0"), page.select_option("#f-band", "0"), page.click("#t-activity")),
            2600,
        ),
        (lambda: page.click("#theme-toggle") or page.click("#theme-toggle"), 2400),  # auto -> light -> dark
        (lambda: (page.click("#theme-toggle"), page.click("#t-overview"), page.click("#lang-toggle")), 3000),  # English
    ]
    frames, durations = [], []
    for action, hold in steps:
        if action:
            action()
            time.sleep(1.2)
        frames.append(grab(page))
        durations.append(hold)
    page.click("#lang-toggle")  # back to French for the app screenshot
    paletted = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in frames]
    out = FIGURES / "demo_dashboard.gif"
    paletted[0].save(out, save_all=True, append_images=paletted[1:], duration=durations, loop=0, optimize=True)
    return out


def screenshot_app(page: Page) -> Path:
    page.goto(APP_URL, wait_until="networkidle")
    page.wait_for_selector("text=Analyse mes parties")
    page.get_by_test_id("stRadio").get_by_text("Profil de démonstration").click()
    time.sleep(1)
    page.get_by_role("button", name="Analyser").click()
    page.wait_for_selector("[data-testid=stMetricLabel] >> text=Ton score", timeout=120000)
    page.get_by_role("tab", name="Pendule").click()
    time.sleep(3)
    out = FIGURES / "app_demo.png"
    grab(page).save(out, optimize=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--chromium", help="path to a Chromium/Chrome executable")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1366, "height": 860}, color_scheme="light", locale="fr-FR")
        for path in (record_dashboard(page), screenshot_app(page)):
            print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1e6:.2f} MB")
        browser.close()


if __name__ == "__main__":
    main()
