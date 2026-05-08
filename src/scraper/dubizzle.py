"""Dubizzle.com.eg property scraper."""

from __future__ import annotations

import re
import logging
from urllib.parse import urljoin

from playwright.async_api import Page

from src.config import DUBIZZLE_BASE, DUBIZZLE_RENT_APARTMENTS
from src.scraper.base import BaseScraper
from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)


class DubizzleScraper(BaseScraper):
    """Scraper for dubizzle.com.eg property rental listings."""

    SOURCE = "dubizzle"

    async def scrape_listings(self, city: str = "cairo", limit: int = 300) -> list[PropertyListing]:
        """
        Scrape rental apartment listings from Dubizzle.

        Args:
            city: City to scrape (key from DUBIZZLE_RENT_APARTMENTS)
            limit: Maximum number of listings to scrape
        """
        base_url = DUBIZZLE_RENT_APARTMENTS.get(city)
        if not base_url:
            available = ", ".join(DUBIZZLE_RENT_APARTMENTS.keys())
            raise ValueError(f"Unknown city: {city}. Available: {available}")

        logger.info("Starting Dubizzle scrape for '%s' (limit=%d)", city, limit)

        page = await self.new_page()
        listings: list[PropertyListing] = []
        page_num = 1

        try:
            while len(listings) < limit:
                # Build paginated URL
                url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
                logger.info("Scraping page %d: %s", page_num, url)

                if not await self.safe_goto(page, url):
                    logger.error("Failed to load page %d, stopping.", page_num)
                    break

                # Scroll to load lazy content
                await self.scroll_page(page, scrolls=5, delay=0.8)

                # Extract listing cards from the page
                new_listings = await self._extract_listing_cards(page, city)

                if not new_listings:
                    logger.info("No listings found on page %d, stopping.", page_num)
                    break

                logger.info("Found %d listings on page %d", len(new_listings), page_num)
                listings.extend(new_listings)

                # Check if we've hit the limit
                if len(listings) >= limit:
                    listings = listings[:limit]
                    break

                # Check for next page
                has_next = await self._has_next_page(page)
                if not has_next:
                    logger.info("No more pages available.")
                    break

                page_num += 1
                await self.polite_delay()

            logger.info("Collected %d listing cards total. Now scraping details...", len(listings))

            # Scrape detail pages for each listing
            for i, listing in enumerate(listings):
                logger.info("[%d/%d] Scraping details: %s", i + 1, len(listings), listing.source_url)
                try:
                    listing = await self.scrape_detail(page, listing)
                    listings[i] = listing
                except Exception as e:
                    logger.warning("Failed to scrape detail for %s: %s", listing.id, e)
                await self.polite_delay()

        finally:
            await page.close()

        self.listings = listings
        logger.info("Dubizzle scrape complete: %d listings", len(listings))
        return listings

    async def _extract_listing_cards(self, page: Page, city: str) -> list[PropertyListing]:
        """Extract listing data from search results page cards."""
        listings = []

        # Strategy: find all <a> links to listing pages and get their parent card containers
        card_links = await page.query_selector_all('a[href*="/en/ad/"]')

        if not card_links:
            logger.warning("No listing card links found on page")
            return []

        # Collect unique listing URLs and their elements
        seen_ids = set()
        raw_cards = []

        for link in card_links:
            href = await link.get_attribute("href")
            if not href or "/en/ad/" not in href:
                continue

            full_url = urljoin(DUBIZZLE_BASE, href)

            # Extract the listing ID from URL (format: ...-ID{number}.html)
            id_match = re.search(r'ID(\d+)\.html', full_url)
            if not id_match:
                continue
            listing_id = id_match.group(1)

            # Deduplicate by ID
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            # Get the text from the link element itself AND try to get the parent card
            text = ""
            try:
                # Try to get text from the closest parent that looks like a card
                # Walk up to find a larger container with more info
                parent = await link.evaluate_handle("""
                    el => {
                        // Walk up to find a container that has price/bed info
                        let node = el;
                        for (let i = 0; i < 5; i++) {
                            if (node.parentElement) {
                                node = node.parentElement;
                                const text = node.innerText || '';
                                // A listing card should have price info
                                if (text.includes('EGP') || text.includes('bed') || text.includes('m²') || text.includes('m2')) {
                                    return node;
                                }
                            }
                        }
                        return el;
                    }
                """)
                text = await parent.inner_text()
                await parent.dispose()
            except Exception:
                try:
                    text = await link.inner_text()
                except Exception:
                    continue

            if text and len(text.strip()) > 5:
                raw_cards.append((link, full_url, listing_id, text.strip()))

        logger.info("Found %d unique listing cards with text", len(raw_cards))

        # Debug: log first card's text
        if raw_cards:
            logger.debug("Sample card text:\n%s", raw_cards[0][3][:300])

        for link, full_url, listing_id, card_text in raw_cards:
            try:
                listing = self._parse_card_text(full_url, listing_id, card_text, city)
                if listing:
                    # Try to get images from the card
                    try:
                        img_els = await link.query_selector_all("img")
                        for img in img_els:
                            src = await img.get_attribute("src")
                            if src and "http" in src and self._is_property_image(src):
                                listing.image_urls.append(src)
                    except Exception:
                        pass
                    listings.append(listing)
            except Exception as e:
                logger.debug("Error parsing card %s: %s", listing_id, e)

        return listings

    def _parse_card_text(self, url: str, listing_id: str, text: str, city: str) -> PropertyListing | None:
        """Parse listing data from card text content."""
        if not text or len(text) < 5:
            return None

        listing = PropertyListing(
            id=listing_id,
            source=self.SOURCE,
            source_url=url,
            location_city=city.replace("-", " ").title(),
        )

        # Parse price from text (e.g., "EGP 80,000" or "EGP 2,300")
        price_match = re.search(r'EGP\s*([\d,]+)', text)
        if price_match:
            try:
                listing.price = float(price_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Parse price period
        text_lower = text.lower()
        if "daily" in text_lower:
            listing.price_period = "daily"
        elif "yearly" in text_lower or "annual" in text_lower:
            listing.price_period = "yearly"
        elif "weekly" in text_lower:
            listing.price_period = "weekly"
        else:
            listing.price_period = "monthly"

        # Parse property type
        if "studio" in text_lower:
            listing.property_type = "studio"
        elif "duplex" in text_lower:
            listing.property_type = "duplex"
        elif "penthouse" in text_lower:
            listing.property_type = "penthouse"
        elif "room" in text_lower and "bed" not in text_lower:
            listing.property_type = "room"
        elif "hotel" in text_lower:
            listing.property_type = "hotel_apartment"
        else:
            listing.property_type = "apartment"

        # Parse beds (e.g., "3 beds" or "2 beds" or "3 bed")
        beds_match = re.search(r'(\d+)\s*bed', text_lower)
        if beds_match:
            listing.bedrooms = int(beds_match.group(1))

        # Parse baths
        baths_match = re.search(r'(\d+)\s*bath', text_lower)
        if baths_match:
            listing.bathrooms = int(baths_match.group(1))

        # Parse area (e.g., "140 m2" or "140 m²")
        area_match = re.search(r'([\d,]+)\s*m[²2]', text)
        if area_match:
            try:
                listing.area_sqm = float(area_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Parse furnished status
        text_nospace = text_lower.replace(" ", "")
        if "furnishedyes" in text_nospace or "furnished\nyes" in text_lower:
            listing.furnished = True
        elif "furnishedno" in text_nospace or "furnished\nno" in text_lower:
            listing.furnished = False

        # Extract title — look for the longest meaningful line
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title_candidates = [
            l for l in lines
            if len(l) > 15
            and not re.match(r'^(EGP|Call|WhatsApp|Chat|Featured|Elite|\d+$)', l, re.IGNORECASE)
            and "ago" not in l.lower()
        ]
        if title_candidates:
            # Pick the longest one as the title
            listing.title = max(title_candidates, key=len)[:200]

        # Extract location — look for area/compound patterns
        # Location lines are short (< 80 chars), contain commas, and don't have property metadata
        for line in lines:
            if (
                "," in line
                and len(line) < 80
                and not re.search(r'EGP|bed|bath|m[²2]|furnished|rent|sale|apartment', line, re.IGNORECASE)
            ):
                listing.location_full = line
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    listing.location_compound = parts[0]
                    listing.location_area = parts[-1]
                break

        return listing

    async def _has_next_page(self, page: Page) -> bool:
        """Check if there's a next page link."""
        current_page_match = re.search(r'page=(\d+)', page.url)
        current = int(current_page_match.group(1)) if current_page_match else 1
        next_page_link = await page.query_selector(f'a[href*="page={current + 1}"]')
        return next_page_link is not None

    async def scrape_detail(self, page: Page, listing: PropertyListing) -> PropertyListing:
        """Scrape the detail page for a single listing to get full info + images."""
        if not await self.safe_goto(page, listing.source_url):
            return listing

        # Wait for images to load
        await self.scroll_page(page, scrolls=3, delay=0.5)

        # === Extract ONLY this listing's gallery images ===
        gallery_images = await self._extract_gallery_images(page)

        if gallery_images:
            listing.image_urls = gallery_images
            logger.info("Extracted %d gallery images for listing %s", len(gallery_images), listing.id)
        else:
            logger.warning("No gallery images found for listing %s, keeping card images", listing.id)

        # === Extract full description ===
        # Try multiple selector strategies for the description
        desc_selectors = [
            '[data-testid="description"]',
            '[class*="description"]',
            '[class*="Description"]',
            'div[class*="content"] p',
            '[class*="detail"] p',
            'section p',
            '[role="main"] p',
        ]
        for selector in desc_selectors:
            try:
                desc_el = await page.query_selector(selector)
                if desc_el:
                    desc_text = await desc_el.inner_text()
                    if desc_text and len(desc_text) > 30:
                        listing.description = desc_text.strip()[:2000]
                        break
            except Exception:
                pass

        # Fallback: try to extract description from page using JS
        if not listing.description:
            try:
                desc = await page.evaluate("""
                    () => {
                        // Look for the largest text block that's not navigation/header
                        const paragraphs = document.querySelectorAll('p, [class*="desc"], [class*="Desc"]');
                        let longest = '';
                        for (const p of paragraphs) {
                            const text = p.innerText || '';
                            if (text.length > longest.length && text.length > 30) {
                                longest = text;
                            }
                        }
                        return longest;
                    }
                """)
                if desc and len(desc) > 30:
                    listing.description = desc.strip()[:2000]
            except Exception:
                pass

        # === Extract additional details from the page text ===
        try:
            body_text = await page.inner_text("body")
        except Exception:
            return listing

        # Try to get floor level if not already set
        if not listing.floor_level:
            floor_match = re.search(r'floor[:\s]*(\d+|ground)', body_text, re.IGNORECASE)
            if floor_match:
                listing.floor_level = floor_match.group(1).lower()

        # Extract features/amenities
        features_keywords = [
            "balcony", "security", "pool", "swimming", "elevator", "lift",
            "garden", "parking", "gym", "ac", "air condition", "central",
            "maid", "storage", "laundry", "internet", "wifi",
            "pets allowed", "natural gas", "electricity", "water meter",
            "landline", "covered parking", "private garden",
        ]
        body_lower = body_text.lower()
        for keyword in features_keywords:
            if keyword in body_lower and keyword not in [f.lower() for f in listing.features]:
                listing.features.append(keyword.title())

        # Extract agent name
        for selector in ['[class*="agent"] [class*="name"]', '[class*="broker"]', '[class*="Agent"]']:
            try:
                agent_el = await page.query_selector(selector)
                if agent_el:
                    name = await agent_el.inner_text()
                    if name and len(name.strip()) > 2:
                        listing.agent_name = name.strip()
                        break
            except Exception:
                pass

        # Extract listed date
        date_match = re.search(r'(\d+\s*(?:minute|hour|day|week|month)s?\s*ago)', body_text, re.IGNORECASE)
        if date_match:
            listing.listed_date = date_match.group(1)

        return listing

    async def _extract_gallery_images(self, page: Page) -> list[str]:
        """
        Extract ONLY the listing's own gallery images.

        Strategy: Click the main image to open the full gallery view,
        which loads ALL the listing's images in a grid. Then collect
        only the images that appeared AFTER clicking (these are the
        listing's actual gallery images, not similar listings).
        """
        import asyncio

        # Step 1: Collect image IDs from BOTTOM of page only (similar listings at Y>2000px)
        # These are the junk images we want to EXCLUDE
        similar_ids = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                const ids = new Set();
                for (const img of imgs) {
                    const match = img.src.match(/thumbnails\\/(\\d+)/);
                    if (match) {
                        const rect = img.getBoundingClientRect();
                        const absY = rect.top + window.scrollY;
                        if (absY > 2000) ids.add(match[1]);
                    }
                }
                return [...ids];
            }
        """)
        exclude_set = set(similar_ids)

        # Step 2: Find and click the main gallery image (the largest one near the top)
        main_img_src = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    if (img.src.includes('images.dubizzle.com.eg') && img.naturalWidth >= 400) {
                        const rect = img.getBoundingClientRect();
                        if (rect.top + window.scrollY < 1000) {
                            return img.src;
                        }
                    }
                }
                return null;
            }
        """)

        if not main_img_src:
            logger.debug("No main gallery image found to click")
            return []

        # Click the image to open the full gallery
        try:
            await page.evaluate("""
                (src) => {
                    const imgs = document.querySelectorAll('img');
                    for (const img of imgs) {
                        if (img.src === src) {
                            img.click();
                            return true;
                        }
                    }
                    return false;
                }
            """, main_img_src)
            await asyncio.sleep(1.5)  # Wait for gallery to fully load
        except Exception as e:
            logger.debug("Failed to click gallery image: %s", e)
            return []

        # Step 3: Collect ALL images now visible — the gallery view loads all listing images
        all_after = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                const results = [];
                const seen = new Set();
                for (const img of imgs) {
                    const src = img.src || '';
                    if (!src.includes('images.dubizzle.com.eg/thumbnails')) continue;
                    const match = src.match(/thumbnails\\/(\\d+)/);
                    if (!match) continue;
                    const imgId = match[1];
                    if (seen.has(imgId)) continue;
                    seen.add(imgId);
                    results.push({id: imgId, url: src, w: img.naturalWidth});
                }
                return results;
            }
        """)

        # Step 4: Identify the listing's own images
        # The NEW images that appeared after clicking are the listing's gallery images
        new_images = [img for img in all_after if img['id'] not in exclude_set]

        if new_images:
            # These are the listing's images — they appeared in the gallery view
            gallery_urls = [img['url'] for img in new_images]
            logger.debug("Found %d NEW gallery images after clicking", len(gallery_urls))
        else:
            # Fallback: all images were already visible — use the ones near the top
            # The initial gallery images (before click) that are in the top area
            gallery_urls = []
            for img in all_after:
                if img['w'] >= 300:  # Only reasonably sized images
                    gallery_urls.append(img['url'])

        # Step 5: Close the gallery view
        try:
            close_btn = await page.query_selector('button[aria-label="Close button"]')
            if close_btn:
                await close_btn.click()
                await asyncio.sleep(0.5)
            else:
                # Try pressing Escape
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
        except Exception:
            pass

        return gallery_urls

    def _is_property_image(self, url: str) -> bool:
        """Check if a URL is likely a property image (not icon/logo/ad)."""
        skip_patterns = [
            "logo", "icon", "avatar", "flag", "badge", "sprite",
            "placeholder", "svg", "gif", "pixel", "tracking",
            "facebook", "google", "twitter", "whatsapp",
            "play-store", "app-store", "advertisement",
            "1x1", "data:image",
        ]
        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in skip_patterns)

    def _get_hq_image_url(self, url: str) -> str:
        """Try to get the highest quality version of an image URL."""
        url = re.sub(r'/s/\d+x\d+/', '/s/1920x1080/', url)
        url = re.sub(r'[?&]w=\d+', '?w=1920', url)
        url = re.sub(r'[?&]h=\d+', '', url)
        url = re.sub(r'[?&]q=\d+', '&q=90', url)
        return url
