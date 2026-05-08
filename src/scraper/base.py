"""Base scraper with shared browser management and utilities."""

from __future__ import annotations

import asyncio
import random
import logging
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from src.config import (
    USER_AGENTS,
    MIN_DELAY,
    MAX_DELAY,
    MAX_RETRIES,
    PAGE_TIMEOUT,
    NAVIGATION_TIMEOUT,
)
from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for property scrapers."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.listings: list[PropertyListing] = []

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def start(self):
        """Launch browser and create context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Africa/Cairo",
        )
        # Stealth: remove webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'ar'] });
        """)
        self._context.set_default_timeout(PAGE_TIMEOUT)
        self._context.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
        logger.info("Browser started (headless=%s)", self.headless)

    async def stop(self):
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped")

    async def new_page(self) -> Page:
        """Create a new page in the browser context."""
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")
        page = await self._context.new_page()
        return page

    async def polite_delay(self):
        """Wait a random amount of time between requests to be polite."""
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        logger.debug("Waiting %.1fs...", delay)
        await asyncio.sleep(delay)

    async def safe_goto(self, page: Page, url: str, retries: int = MAX_RETRIES) -> bool:
        """Navigate to URL with retries and error handling."""
        for attempt in range(1, retries + 1):
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                if response and response.ok:
                    # Wait a bit for dynamic content to load
                    await asyncio.sleep(1)
                    return True
                else:
                    status = response.status if response else "no response"
                    logger.warning("Got status %s for %s (attempt %d/%d)", status, url, attempt, retries)
            except Exception as e:
                logger.warning("Error navigating to %s (attempt %d/%d): %s", url, attempt, retries, e)

            if attempt < retries:
                wait = 2 ** attempt + random.random()
                logger.info("Retrying in %.1fs...", wait)
                await asyncio.sleep(wait)

        logger.error("Failed to load %s after %d attempts", url, retries)
        return False

    async def scroll_page(self, page: Page, scrolls: int = 3, delay: float = 1.0):
        """Scroll down the page to trigger lazy loading."""
        for i in range(scrolls):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(delay)
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

    @abstractmethod
    async def scrape_listings(self, city: str, limit: int = 300) -> list[PropertyListing]:
        """Scrape property listings. Must be implemented by subclasses."""
        ...

    @abstractmethod
    async def scrape_detail(self, page: Page, listing: PropertyListing) -> PropertyListing:
        """Scrape detail page for a single listing. Must be implemented by subclasses."""
        ...
