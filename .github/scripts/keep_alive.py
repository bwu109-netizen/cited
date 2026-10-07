"""Keep the Streamlit Community Cloud app awake (run by .github/workflows/keep-alive.yml).

Opens APP_URL in headless Chromium. If Streamlit shows its sleep page, clicks the wake-up button
("Yes, get this app back up!") and waits for the app to load. Succeeds only when the product name is
visible in the page or one of its frames; otherwise exits 1 so the workflow fails and GitHub emails.
"""
import os
import re
import sys
import time

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

URL = os.environ.get("APP_URL", "").strip()
NAMES = ("财报数字核验", "Earnings Verifier")
WAKE = re.compile(r"get this app back up|wake (it|this app) up", re.I)
LOAD_SECONDS = 300  # a cold start (pip install + boot) can take a few minutes


def name_visible(page):
    for frame in page.frames:  # the app runs in nested iframes
        try:
            text = frame.evaluate("() => document.title + '\\n' + (document.body ? document.body.innerText : '')")
        except Exception:  # noqa: BLE001  (frame navigated away while reading)
            continue
        if any(n in text for n in NAMES):
            return True
    return False


def main():
    if not URL:
        sys.exit("APP_URL is empty: set the repository variable APP_URL (Settings → Secrets and variables → Actions → Variables)")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")  # Google Chrome preinstalled on GitHub's Ubuntu runners
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        print("opened", page.url)
        woke = False
        deadline = time.time() + LOAD_SECONDS
        while time.time() < deadline:
            if name_visible(page):
                print(f"OK: product name visible{' after waking the app' if woke else ''}")
                browser.close()
                return
            button = page.get_by_role("button", name=WAKE)
            if not woke and button.count():
                print("app is asleep: clicking", repr(button.first.inner_text().strip()))
                button.first.click()
                woke = True
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PWTimeout:
                pass
            time.sleep(5)
        page.screenshot(path="keep-alive-failure.png", full_page=True)
        print("FAIL: product name not visible after", LOAD_SECONDS, "s; last URL", page.url)
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
