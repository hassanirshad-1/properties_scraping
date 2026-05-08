"""AI-powered image analysis using OpenAI-compatible Vision API (SwiftRouter / Kimi K2.5)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path

from src.config import AI_BASE_URL, AI_API_KEY, AI_MODEL, MAX_IMAGES_TO_ANALYZE
from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)

# Extremely concise prompt to minimize thinking time and avoid timeouts
ANALYSIS_PROMPT = """Analyze these Egypt property photos and return ONLY a JSON object.
No thinking, no markdown, no explanation. Just the JSON.

Fields:
{
"estimated_floor": "ground|1-2|3-4|5-7|8+",
"view_type": "garden|street|pool|city|compound",
"sun_direction": "north|south|east|west",
"interior_quality": "luxury|high-end|modern|standard",
"furniture_style": "furnished-modern|furnished-classic|unfurnished",
"notable_features": ["list"],
"search_tags": ["list"],
"overall_vibe": "1 sentence"
}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON from AI response, handling markdown fences and thinking text."""
    text = text.strip()

    # Strategy 1: Remove markdown code fences
    if "```" in text:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Strategy 2: Find the largest valid JSON object {...}
    brace_depth = 0
    start_idx = None
    json_objects = []

    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                start_idx = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                candidate = text[start_idx:i + 1]
                try:
                    parsed = json.loads(candidate)
                    json_objects.append(parsed)
                except json.JSONDecodeError:
                    pass
                start_idx = None

    if json_objects:
        return max(json_objects, key=lambda x: len(json.dumps(x)))

    # Strategy 3: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def analyze_listing_images(
    listing: PropertyListing,
    api_key: str | None = None,
) -> dict | None:
    """
    Analyze images for a single listing using OpenAI-compatible Vision API.

    Args:
        listing: PropertyListing with local_images populated
        api_key: API key (falls back to env var)

    Returns:
        Analysis dict or None if failed
    """
    key = api_key or AI_API_KEY
    if not key:
        logger.warning("No API key provided. Skipping analysis.")
        return None

    images_to_analyze = listing.local_images[:MAX_IMAGES_TO_ANALYZE]
    if not images_to_analyze:
        logger.debug("No local images for listing %s, skipping.", listing.id)
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=AI_BASE_URL)

        # Build content: prompt + base64 images
        content = [{"type": "text", "text": ANALYSIS_PROMPT}]

        for img_path in images_to_analyze:
            path = Path(img_path)
            if path.exists():
                img_bytes = path.read_bytes()
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                suffix = path.suffix.lower()
                mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".png": "image/png", ".webp": "image/webp"}
                mime_type = mime_map.get(suffix, "image/jpeg")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                })

        if len(content) <= 1:
            logger.debug("No valid images for listing %s", listing.id)
            return None

        # Call the Vision API
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=2000,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        analysis = _extract_json(raw)

        if analysis:
            logger.info(
                "Analyzed listing %s (confidence: %s, tags: %d)",
                listing.id,
                analysis.get("confidence", "?"),
                len(analysis.get("search_tags", [])),
            )
            return analysis
        else:
            logger.warning("No valid JSON in AI response for listing %s", listing.id)
            logger.info("RAW AI RESPONSE FOR DEBUGGING:\n%s", raw)
            return None

    except Exception as e:
        logger.warning("AI analysis failed for listing %s: %s", listing.id, e)
        return None


async def analyze_all_listings(
    listings: list[PropertyListing],
    api_key: str | None = None,
    delay: float = 2.0,
) -> list[PropertyListing]:
    """
    Run AI analysis on all listings that have downloaded images.

    Args:
        listings: List of PropertyListing with local_images
        api_key: API key
        delay: Delay between API calls (seconds)
    """
    key = api_key or AI_API_KEY
    if not key:
        logger.error("No API key. Set AGENTROUTER_API_KEY env var or pass --api-key.")
        return listings

    analyzed = 0
    skipped = 0
    failed = 0

    for i, listing in enumerate(listings):
        if not listing.local_images:
            skipped += 1
            continue

        if listing.ai_analysis:
            logger.debug("Listing %s already analyzed, skipping.", listing.id)
            skipped += 1
            continue

        logger.info("[%d/%d] Analyzing listing %s (%d images)...",
                     i + 1, len(listings), listing.id, len(listing.local_images))
        analysis = await analyze_listing_images(listing, api_key=key)

        if analysis:
            listing.ai_analysis = analysis
            analyzed += 1
        else:
            failed += 1

        # Rate limit
        await asyncio.sleep(delay)

    logger.info("AI analysis complete: %d analyzed, %d skipped, %d failed",
                analyzed, skipped, failed)
    return listings
