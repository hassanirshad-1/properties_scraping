"""Async image downloader for property listings."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import httpx
from PIL import Image

from src.config import IMAGES_DIR, MAX_CONCURRENT_DOWNLOADS, MAX_IMAGE_WIDTH, USER_AGENTS
from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)


async def download_images_for_listings(
    listings: list[PropertyListing],
    output_dir: Path | None = None,
    max_concurrent: int = MAX_CONCURRENT_DOWNLOADS,
) -> list[PropertyListing]:
    """
    Download all images for a list of listings.

    Args:
        listings: List of PropertyListing with image_urls populated
        output_dir: Base directory for images (default: output/images/)
        max_concurrent: Max parallel downloads

    Returns:
        Updated listings with local_images paths filled in
    """
    output_dir = output_dir or IMAGES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(max_concurrent)
    total_images = sum(len(l.image_urls) for l in listings)
    logger.info("Downloading images for %d listings (%d images total)", len(listings), total_images)

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENTS[0]},
    ) as client:
        for i, listing in enumerate(listings):
            if not listing.image_urls:
                continue

            listing_dir = output_dir / listing.id
            listing_dir.mkdir(parents=True, exist_ok=True)

            local_paths = []
            tasks = []

            for j, img_url in enumerate(listing.image_urls):
                ext = _get_extension(img_url)
                filename = f"{j + 1}{ext}"
                filepath = listing_dir / filename

                # Skip if already downloaded
                if filepath.exists() and filepath.stat().st_size > 1000:
                    local_paths.append(str(filepath))
                    continue

                tasks.append(
                    _download_single(client, semaphore, img_url, filepath, local_paths)
                )

            if tasks:
                await asyncio.gather(*tasks)

            listing.local_images = sorted(local_paths)
            logger.info(
                "[%d/%d] %s: %d/%d images downloaded",
                i + 1, len(listings), listing.id,
                len(listing.local_images), len(listing.image_urls),
            )

    return listings


async def _download_single(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    filepath: Path,
    local_paths: list[str],
):
    """Download a single image with concurrency control."""
    async with semaphore:
        try:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                logger.debug("Skipping non-image URL: %s (content-type: %s)", url, content_type)
                return

            filepath.write_bytes(response.content)

            # Resize if too large
            _resize_if_needed(filepath)

            local_paths.append(str(filepath))

        except httpx.HTTPStatusError as e:
            logger.debug("HTTP error downloading %s: %s", url, e.response.status_code)
        except Exception as e:
            logger.debug("Error downloading %s: %s", url, e)


def _resize_if_needed(filepath: Path):
    """Resize image if wider than MAX_IMAGE_WIDTH to save disk space."""
    try:
        with Image.open(filepath) as img:
            if img.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / img.width
                new_size = (MAX_IMAGE_WIDTH, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                img.save(filepath, quality=85, optimize=True)
    except Exception:
        pass  # If resize fails, keep original


def _get_extension(url: str) -> str:
    """Extract file extension from URL."""
    # Remove query parameters
    clean = url.split("?")[0].split("#")[0]
    match = re.search(r'\.(jpe?g|png|webp|avif)', clean, re.IGNORECASE)
    if match:
        ext = match.group(0).lower()
        return ext if ext.startswith(".") else f".{ext}"
    return ".jpg"  # Default
