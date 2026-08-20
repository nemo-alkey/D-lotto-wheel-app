#!/usr/bin/env python3
"""
selenium_scraper.py — Selenium-based scraper for JavaScript-rendered MyLotto pages.

Uses headless Chrome to load pages, waits for dynamic content to render,
then extracts all draw results from the page.

Requires: selenium, webdriver-manager

Usage:
    from selenium_scraper import selenium_scrape_results
    draws = selenium_scrape_results("https://mylotto.co.nz/results/lotto")
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any

SELENIUM_AVAILABLE = True
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        from webdriver_manager.chrome import ChromeDriverManager

        HAS_WDM = True
    except ImportError:
        HAS_WDM = False
except ImportError:
    SELENIUM_AVAILABLE = False


def _get_driver(headless: bool = True) -> webdriver.Chrome | None:
    """Create a headless Chrome driver."""
    if not SELENIUM_AVAILABLE:
        print(
            "Selenium not installed. Install with: pip install selenium webdriver-manager"
        )
        return None

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    try:
        if HAS_WDM:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            # Try to use chromedriver from PATH or SELENIUM_CHROME_BINARY
            binary_location = os.environ.get("SELENIUM_CHROME_BINARY", "")
            if binary_location:
                options.binary_location = binary_location
            service = Service()  # uses PATH
            driver = webdriver.Chrome(service=service, options=options)
            return driver
    except Exception as e:
        # Provide a clear, user-friendly error message
        print("=" * 72)
        print("  SELENIUM / CHROMEDRIVER SETUP ERROR")
        print("=" * 72)
        print(f"Failed to create Chrome driver: {e}")
        print()
        print("To use Selenium-based scraping, you need Chrome for Testing")
        print("and the matching ChromeDriver.  Choose one of:")
        print()
        print("Option 1 — Use ChromeDriverManager (automatic):")
        print("    pip install selenium webdriver-manager")
        print("    # No further config needed — ChromeDriverManager downloads")
        print("    # the correct chromedriver for your installed Chrome.")
        print()
        print("Option 2 — Manual Chromedriver (Codespaces / headless servers):")
        print("    # Install Chrome for Testing")
        print("    wget -q -O /tmp/chrome.deb \\")
        print(
            "      https://dl.google.com/linux/direct/"
            "google-chrome-stable_current_amd64.deb"
        )
        print("    sudo apt-get update && sudo apt-get install -y \\")
        print("      /tmp/chrome.deb")
        print()
        print("    # Download matching chromedriver")
        print(
            "    CHROME_VER=$(google-chrome --version | grep -oP '[0-9]+(?=\\.)' | head -1)"
        )
        print("    wget -q -O /tmp/chromedriver.zip \\")
        print(
            "      https://storage.googleapis.com/chrome-for-testing-public/"
            "${CHROME_VER}/linux64/chromedriver-linux64.zip"
        )
        print("    sudo unzip -o /tmp/chromedriver.zip -d /usr/local/bin/")
        print("    sudo chmod +x /usr/local/bin/chromedriver-linux64/chromedriver")
        print("    sudo ln -sf /usr/local/bin/chromedriver-linux64/chromedriver \\")
        print("      /usr/local/bin/chromedriver")
        print()
        print("Option 3 — Custom Chrome binary location:")
        print("    Set the SELENIUM_CHROME_BINARY environment variable to the")
        print("    full path of your Chrome/Chromium executable, e.g.:")
        print("    export SELENIUM_CHROME_BINARY=/usr/bin/google-chrome")
        print()
        print("=" * 72)
        return None
    # The try block above falls through here without a value when the
    # HAS_WDM branch completes; make the implicit None return explicit
    # to satisfy the declared "webdriver.Chrome | None" contract.
    return None


def selenium_scrape_results(
    url: str = "https://mylotto.co.nz/results/lotto",
    wait_element_id: str = "results-container",
    headless: bool = True,
) -> list[dict[str, Any]]:
    """Scrape draw results from a JavaScript-rendered MyLotto page.

    Parameters
    ----------
    url : str
        URL of the results page.
    wait_element_id : str
        CSS selector or ID of the element to wait for before scraping.
    headless : bool
        Run Chrome in headless mode (default True).

    Returns
    -------
    list[dict]
        Each dict: draw_date, numbers (list[6 ints]), bonus, powerball.
    """
    driver = _get_driver(headless=headless)
    if driver is None:
        return []

    draws: list[dict[str, Any]] = []

    try:
        driver.get(url)

        # Wait for dynamic content to load
        try:
            WebDriverWait(driver, 15).until(
                expected_conditions.presence_of_element_located(
                    (By.ID, wait_element_id)
                )
            )
        except Exception:
            # Fallback: wait for any result-like element
            with contextlib.suppress(Exception):
                WebDriverWait(driver, 10).until(
                    expected_conditions.presence_of_element_located(
                        (By.CSS_SELECTOR, "[class*='result'], [class*='draw'], article")
                    )
                )

        # Small extra wait for JS rendering
        time.sleep(2)

        # Find result cards
        import re

        from bs4 import BeautifulSoup

        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")

        number_re = re.compile(r"\b([1-9]|[12]\d|3[0-9]|40)\b")

        cards = (
            soup.find_all(class_=re.compile(r"result.?card", re.I))
            or soup.find_all("article")
            or soup.find_all(class_=re.compile(r"draw", re.I))
        )

        for card in cards:
            # Date
            date_el = card.find("time") or card.find("h3")
            date_str = date_el.get_text(strip=True) if date_el else None
            if not date_str:
                continue

            # Numbers
            full_text = card.get_text(separator=" ", strip=True)
            all_nums = [
                int(m) for m in number_re.findall(full_text) if 1 <= int(m) <= 40
            ]
            seen: set[int] = set()
            numbers: list[int] = []
            for n in all_nums:
                if n not in seen and len(numbers) < 6:
                    numbers.append(n)
                    seen.add(n)

            if len(numbers) != 6:
                continue

            # Bonus
            bonus = 0
            bonus_el = card.find(string=re.compile(r"bonus", re.I))
            if bonus_el:
                bp = bonus_el.find_parent()
                if bp:
                    bm = number_re.findall(bp.get_text())
                    if bm:
                        bonus = int(bm[-1])

            # Powerball
            powerball = 0
            pb_el = card.find(string=re.compile(r"powerball", re.I))
            if pb_el:
                pp = pb_el.find_parent()
                if pp:
                    pm = re.findall(r"\b(10|[1-9])\b", pp.get_text())
                    if pm:
                        powerball = int(pm[-1])

            draws.append(
                {
                    "draw_date": date_str,
                    "numbers": sorted(numbers),
                    "bonus": bonus if 1 <= bonus <= 40 else 0,
                    "powerball": powerball if 1 <= powerball <= 10 else 0,
                }
            )

    except Exception as e:
        print(f"Scraping error: {e}")
    finally:
        driver.quit()

    return draws


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Testing Selenium scraper...")
    results = selenium_scrape_results()
    if results:
        print(f"Found {len(results)} draw(s):")
        for r in results[:3]:
            print(
                f"  {r['draw_date']}: {r['numbers']} B:{r['bonus']} PB:{r['powerball']}"
            )
    else:
        print("No results found (Chrome/WebDriver may not be installed).")
