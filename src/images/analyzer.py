"""AI-powered image analysis using Google Gemini Vision API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

from src.config import GEMINI_API_KEY, GEMINI_MODEL, MAX_IMAGES_TO_ANALYZE
from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)

# The analysis prompt sent to Gemini Vision
ANALYSIS_PROMPT = """You are a real estate image analyst for the Egyptian property market. Analyze these property images and provide a structured JSON response with the following fields:

1. "estimated_floor": Estimate which floor this apartment is on based on window views, balcony height, and surroundings (e.g., "ground", "1-2", "3-4", "5-7", "8+", "unknown")
2. "view_type": What does the property overlook? (e.g., "garden", "street", "pool", "desert", "city", "compound", "parking", "nile", "unknown")
3. "view_description": Brief description of the view from the property
4. "sun_direction": Based on shadows, light, and orientation clues, estimate sun exposure (e.g., "north-facing (shaded)", "south-facing (sunny)", "east-facing", "west-facing", "unknown")
5. "building_condition": Is this a new or old building? (e.g., "new", "modern", "well-maintained", "older", "needs-renovation")
6. "interior_quality": Rate the interior finishing (e.g., "luxury", "modern", "standard", "basic", "unfinished")
7. "notable_features": List any notable visual features spotted in images (e.g., ["marble floors", "recessed lighting", "open kitchen", "large balcony", "en-suite bathroom"])
8. "neighborhood_vibe": Describe the surrounding area if visible (e.g., "gated compound", "urban street", "quiet residential", "near commercial area")
9. "confidence": Your confidence in this analysis (0.0 to 1.0)

Respond ONLY with valid JSON. No markdown, no explanation. Just the JSON object."""


async def analyze_listing_images(
    listing: PropertyListing,
    api_key: str | None = None,
) -> dict | None:
    """
    Analyze images for a single listing using Gemini Vision.

    Args:
        listing: PropertyListing with local_images populated
        api_key: Gemini API key (falls back to env var)

    Returns:
        Analysis dict or None if failed
    """
    key = api_key or GEMINI_API_KEY
    if not key:
        logger.warning("No Gemini API key provided. Skipping analysis.")
        return None

    images_to_analyze = listing.local_images[:MAX_IMAGES_TO_ANALYZE]
    if not images_to_analyze:
        logger.debug("No local images for listing %s, skipping analysis.", listing.id)
        return None

    try:
        from google import genai

        client = genai.Client(api_key=key)

        # Build the content parts: prompt + images
        parts = [ANALYSIS_PROMPT]

        for img_path in images_to_analyze:
            path = Path(img_path)
            if path.exists():
                # Upload image as inline data
                img_bytes = path.read_bytes()
                # Determine mime type
                suffix = path.suffix.lower()
                mime_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                }
                mime_type = mime_map.get(suffix, "image/jpeg")
                parts.append(
                    genai.types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                )

        if len(parts) <= 1:
            logger.debug("No valid images to analyze for listing %s", listing.id)
            return None

        # Call Gemini Vision
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=parts,
        )

        # Parse the JSON response
        response_text = response.text.strip()

        # Clean up response — remove markdown code fences if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

        analysis = json.loads(response_text)
        logger.info("Successfully analyzed listing %s (confidence: %s)", listing.id, analysis.get("confidence", "?"))
        return analysis

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse Gemini response for listing %s: %s", listing.id, e)
        return None
    except Exception as e:
        logger.warning("Gemini analysis failed for listing %s: %s", listing.id, e)
        return None


async def analyze_all_listings(
    listings: list[PropertyListing],
    api_key: str | None = None,
    delay: float = 1.0,
) -> list[PropertyListing]:
    """
    Run AI analysis on all listings that have downloaded images.

    Args:
        listings: List of PropertyListing with local_images
        api_key: Gemini API key
        delay: Delay between API calls (seconds)
    """
    key = api_key or GEMINI_API_KEY
    if not key:
        logger.error("No Gemini API key. Set GEMINI_API_KEY env var or pass --api-key.")
        return listings

    analyzed = 0
    skipped = 0

    for i, listing in enumerate(listings):
        if not listing.local_images:
            skipped += 1
            continue

        if listing.ai_analysis:
            logger.debug("Listing %s already analyzed, skipping.", listing.id)
            skipped += 1
            continue

        logger.info("[%d/%d] Analyzing listing %s...", i + 1, len(listings), listing.id)
        analysis = await analyze_listing_images(listing, api_key=key)

        if analysis:
            listing.ai_analysis = analysis
            analyzed += 1
        else:
            skipped += 1

        # Rate limit
        await asyncio.sleep(delay)

    logger.info("AI analysis complete: %d analyzed, %d skipped", analyzed, skipped)
    return listings
