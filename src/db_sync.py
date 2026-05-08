"""
Database sync service — pushes scraped + AI-analyzed listings into Bawab's Postgres DB.

Maps our PropertyListing model to Bawab's Drizzle schema:
  - properties table
  - property_photos table

Also creates a "system scraper" user as the owner of all scraped listings.
"""

from __future__ import annotations

import json
import re
import uuid
import logging
from datetime import datetime, timezone

import asyncpg

from src.scraper.models import PropertyListing

logger = logging.getLogger(__name__)


# ── Column mapping helpers ──────────────────────────────────────────────────

TYPE_MAP = {
    "apartment": "APARTMENT",
    "villa": "VILLA",
    "studio": "STUDIO",
    "duplex": "DUPLEX",
    "penthouse": "PENTHOUSE",
    "chalet": "CHALET",
    "room": "APARTMENT",         # fallback
    "hotel_apartment": "APARTMENT",
}

FURNISH_MAP = {
    True: "FULLY_FURNISHED",
    False: "UNFURNISHED",
    None: "UNFURNISHED",
}


def _floor_int(ai: dict) -> int | None:
    """Convert AI estimated_floor string to an integer."""
    raw = ai.get("estimated_floor", "")
    if not raw:
        return None
    if "ground" in raw.lower():
        return 0
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def _view_types(ai: dict) -> list[str]:
    """Normalize AI view_type to a list of strings."""
    vt = ai.get("view_type", [])
    if isinstance(vt, str):
        return [vt]
    if isinstance(vt, list):
        return vt
    return []


def _bool_feature(listing: PropertyListing, ai: dict, keywords: list[str], ai_key: str | None = None) -> bool:
    """Check features list + AI analysis for a boolean property."""
    features_lower = [f.lower() for f in listing.features]
    for kw in keywords:
        if kw in features_lower:
            return True
    if ai_key and ai.get(ai_key):
        return True
    # Also check notable_features from AI
    notable = [f.lower() for f in ai.get("notable_features", [])]
    for kw in keywords:
        if any(kw in n for n in notable):
            return True
    return False


# ── Sync Service ────────────────────────────────────────────────────────────

class BawabSyncService:
    """Syncs scraped PropertyListings into Bawab's Postgres database."""

    SCRAPER_CLERK_ID = "scraper_system_user"
    SCRAPER_USER_ID = "scraper-system-00000000"

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        return self._pool

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def ensure_scraper_user(self):
        """Create the system 'scraper' user that owns all auto-imported listings."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT id FROM users WHERE id = $1", self.SCRAPER_USER_ID
            )
            if not exists:
                await conn.execute("""
                    INSERT INTO users (id, clerk_id, email, role, name_ar, name_en, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, true)
                    ON CONFLICT (id) DO NOTHING
                """,
                    self.SCRAPER_USER_ID,
                    self.SCRAPER_CLERK_ID,
                    "scraper@bawab.app",
                    "OWNER",
                    "نظام الاستيراد التلقائي",   # "Auto-import system" in Arabic
                    "Auto-Import System",
                )
                # Create owner profile
                await conn.execute("""
                    INSERT INTO owner_profiles (id, user_id, company_name, is_company, ownership_verified)
                    VALUES ($1, $2, $3, true, true)
                    ON CONFLICT DO NOTHING
                """,
                    str(uuid.uuid4()),
                    self.SCRAPER_USER_ID,
                    "Bawab Auto-Scraper",
                )
                logger.info("Created system scraper user in Bawab DB")

    async def sync_listings(self, listings: list[PropertyListing]) -> dict:
        """
        Sync a batch of listings into Bawab's database.

        Returns stats: {inserted, skipped, failed}
        """
        await self.ensure_scraper_user()
        pool = await self.get_pool()

        stats = {"inserted": 0, "skipped": 0, "failed": 0}

        async with pool.acquire() as conn:
            for listing in listings:
                try:
                    inserted = await self._sync_one(conn, listing)
                    if inserted:
                        stats["inserted"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("Failed to sync listing %s: %s", listing.id, e)
                    stats["failed"] += 1

        logger.info(
            "Sync complete: %d inserted, %d skipped, %d failed",
            stats["inserted"], stats["skipped"], stats["failed"],
        )
        return stats

    async def _sync_one(self, conn: asyncpg.Connection, listing: PropertyListing) -> bool:
        """Insert a single listing. Returns True if inserted, False if skipped (duplicate)."""

        # === DEDUPLICATION (3 layers) ===
        
        # Layer 1: Check by source_id (Dubizzle listing ID — most reliable)
        if listing.id:
            existing = await conn.fetchval(
                "SELECT id FROM properties WHERE source_id = $1 LIMIT 1",
                listing.id,
            )
            if existing:
                logger.debug("Listing %s already in DB (source_id match → %s), skipping.", listing.id, existing)
                return False

        # Layer 2: Check by source_url
        if listing.source_url:
            existing = await conn.fetchval(
                "SELECT id FROM properties WHERE source_url = $1 LIMIT 1",
                listing.source_url,
            )
            if existing:
                logger.debug("Listing %s already in DB (source_url match → %s), skipping.", listing.id, existing)
                return False

        # Layer 3: Check by title + price + area (catches re-listed properties)
        if listing.title and listing.price:
            existing = await conn.fetchval(
                "SELECT id FROM properties WHERE title_en = $1 AND price = $2 AND area = $3 LIMIT 1",
                listing.title, listing.price, listing.area_sqm,
            )
            if existing:
                logger.debug("Listing %s already in DB (title+price match → %s), skipping.", listing.id, existing)
                return False

        ai = listing.ai_analysis or {}

        property_id = str(uuid.uuid4())

        await conn.execute("""
            INSERT INTO properties (
                id, owner_id,
                title_ar, title_en, description_ar, description_en,
                type, purpose, status,
                governorate, city, district, street,
                area, bedrooms, bathrooms, living_rooms, balconies,
                price, currency, payment_frequency,
                furnished, floor,
                view_type, facing, noise_level, kitchen_type,
                has_parking, has_elevator, has_security,
                has_garden, has_pool, has_split_ac,
                is_featured, is_highlighted, is_boosted, is_paid,
                view_count, connection_count,
                source_url, source_id, ai_tags, ai_vibe, ai_analysis,
                created_at, updated_at, published_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
                $31, $32, $33, $34, $35, $36, $37, $38, $39,
                $40, $41, $42, $43, $44::jsonb,
                NOW(), NOW(), NOW()
            )
        """,
            property_id,
            self.SCRAPER_USER_ID,
            # title_ar / title_en
            listing.title_ar or listing.title or "بدون عنوان",
            listing.title or "",
            # description_ar / description_en
            listing.description_ar or listing.description or "لا يوجد وصف",
            listing.description or "",
            # type, purpose, status
            TYPE_MAP.get(listing.property_type, "APARTMENT"),
            "RENT",
            "ACTIVE",
            # governorate, city, district, street
            "القاهرة",  # Cairo in Arabic
            listing.location_city or "Cairo",
            listing.location_area or listing.location_compound or "",
            None,  # street
            # area, bedrooms, bathrooms, living_rooms, balconies
            listing.area_sqm or 0.0,
            listing.bedrooms or 1,
            listing.bathrooms or 1,
            1,  # living_rooms default
            1 if _bool_feature(listing, ai, ["balcony"]) else 0,
            # price, currency, payment_frequency
            listing.price or 0.0,
            "EGP",
            listing.price_period or "monthly",
            # furnished, floor
            FURNISH_MAP.get(listing.furnished, "UNFURNISHED"),
            _floor_int(ai),
            # view_type (text[]), facing, noise_level, kitchen_type
            _view_types(ai),
            ai.get("sun_direction"),
            ai.get("noise_level_estimate") or ai.get("neighborhood_vibe"),
            ai.get("kitchen_type"),
            # boolean features
            _bool_feature(listing, ai, ["parking"], "parking_visible"),
            _bool_feature(listing, ai, ["elevator", "lift"], "elevator_building"),
            _bool_feature(listing, ai, ["security"], "security_visible"),
            _bool_feature(listing, ai, ["garden"]),
            _bool_feature(listing, ai, ["pool", "swimming"], "pool_visible"),
            _bool_feature(listing, ai, ["ac", "air condition"]),
            # monetization flags (all false for scraped)
            False, False, False, False,
            # counters
            0, 0,
            # AI / source columns
            listing.source_url,
            listing.id,
            ai.get("search_tags", []),
            ai.get("overall_vibe"),
            json.dumps(ai) if ai else None,
        )

        # Insert photos
        for i, photo_url in enumerate(listing.image_urls[:20]):
            try:
                await conn.execute("""
                    INSERT INTO property_photos (id, property_id, url, "order", is_verified, created_at)
                    VALUES ($1, $2, $3, $4, false, NOW())
                """,
                    str(uuid.uuid4()),
                    property_id,
                    photo_url,
                    i,
                )
            except Exception as e:
                logger.debug("Failed to insert photo %d for %s: %s", i, listing.id, e)

        logger.info("Inserted listing %s → property %s (%d photos)", listing.id, property_id, len(listing.image_urls[:20]))
        return True
