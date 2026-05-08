"""Data models for property listings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class PropertyListing:
    """A single property rental listing scraped from a source site."""

    # === Identity ===
    id: str = ""                          # Unique ID from source site
    source: str = ""                      # "dubizzle" | "bayut" | "propertyfinder"
    source_url: str = ""                  # Original listing URL

    # === Core Info ===
    title: str = ""                       # Listing title/headline
    description: str = ""                 # Full description text

    # === Pricing ===
    price: float = 0.0                    # Rent price
    price_currency: str = "EGP"           # Currency code
    price_period: str = "monthly"         # "monthly" | "daily" | "yearly" | "weekly"

    # === Property Details ===
    property_type: str = "apartment"      # "apartment" | "studio" | "villa" | "duplex" | "penthouse" | "room"
    bedrooms: int = 0
    bathrooms: int = 0
    area_sqm: float = 0.0
    floor_level: str | None = None        # "ground" | "1" | "2" | etc.
    furnished: bool | None = None         # True = furnished, False = unfurnished, None = unknown

    # === Location ===
    location_city: str = ""               # "Cairo" | "Giza" | "Alexandria"
    location_area: str = ""               # "New Cairo" | "Madinaty" | "Sheikh Zayed" etc.
    location_compound: str | None = None  # Compound name if applicable
    location_full: str = ""               # Full location string as shown on site

    # === Features ===
    features: list[str] = field(default_factory=list)  # ["balcony", "security", "pool", "elevator"]

    # === Images ===
    image_urls: list[str] = field(default_factory=list)     # Original image URLs from source
    local_images: list[str] = field(default_factory=list)   # Local file paths after download

    # === Agent/Owner ===
    agent_name: str | None = None
    agent_type: str | None = None  # "agent" | "owner" | "company"

    # === Metadata ===
    listed_date: str | None = None        # When listing was posted
    scraped_at: str = ""                  # ISO timestamp of when we scraped it

    # === AI Analysis (Phase 2) ===
    ai_analysis: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyListing:
        """Create a PropertyListing from a dictionary."""
        # Filter out unknown keys
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @property
    def price_display(self) -> str:
        """Human-readable price display."""
        return f"{self.price_currency} {self.price:,.0f}/{self.price_period}"

    @property
    def summary(self) -> str:
        """One-line summary of the listing."""
        parts = [self.property_type.title()]
        if self.bedrooms:
            parts.append(f"{self.bedrooms}BR")
        if self.bathrooms:
            parts.append(f"{self.bathrooms}BA")
        if self.area_sqm:
            parts.append(f"{self.area_sqm:.0f}m²")
        details = " | ".join(parts)
        return f"[{details}] {self.title[:60]} — {self.price_display} in {self.location_area or self.location_city}"
