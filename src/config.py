"""Configuration for the property scraper."""

import os
from pathlib import Path

# === Paths ===
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
LISTINGS_FILE = OUTPUT_DIR / "listings.json"
SUMMARY_FILE = OUTPUT_DIR / "listings_summary.csv"
STATS_FILE = OUTPUT_DIR / "stats.json"

# === Scraping Settings ===
# Delay between requests (seconds) — be polite!
MIN_DELAY = 2.0
MAX_DELAY = 4.0

# Max retries for failed requests
MAX_RETRIES = 3

# Playwright timeout (ms)
PAGE_TIMEOUT = 30000
NAVIGATION_TIMEOUT = 60000

# Max concurrent image downloads
MAX_CONCURRENT_DOWNLOADS = 5

# Max image width (resize larger images to save space)
MAX_IMAGE_WIDTH = 1920

# === User Agent Pool ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# === Dubizzle URLs ===
DUBIZZLE_BASE = "https://www.dubizzle.com.eg"
DUBIZZLE_RENT_APARTMENTS = {
    "cairo": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/cairo/",
    "giza": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/giza/",
    "alexandria": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/alexandria/",
    "new-cairo": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/new-cairo/",
    "madinaty": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/madinaty/",
    "sheikh-zayed": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/sheikh-zayed/",
    "6th-of-october": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/6th-of-october/",
    "nasr-city": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/nasr-city/",
    "maadi": f"{DUBIZZLE_BASE}/en/properties/apartments-duplex-for-rent/maadi/",
}

# === Bayut URLs ===
BAYUT_BASE = "https://www.bayut.eg"
BAYUT_RENT_APARTMENTS = {
    "cairo": f"{BAYUT_BASE}/en/to-rent/apartments/cairo/",
    "giza": f"{BAYUT_BASE}/en/to-rent/apartments/giza/",
    "alexandria": f"{BAYUT_BASE}/en/to-rent/apartments/alexandria/",
}

# === AI Analysis ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"

# Images to analyze per listing (to control costs)
MAX_IMAGES_TO_ANALYZE = 5
