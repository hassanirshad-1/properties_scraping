# 🏠 Egypt Property Scraper

A powerful Python CLI tool that scrapes Egyptian property rental listings from **dubizzle.com.eg**, downloads all property images, and outputs structured JSON + CSV data.

## ✨ Features

- 🔍 **Smart Scraping** — Extracts title, price, bedrooms, bathrooms, area, location, description, features, and listed date
- 🖼️ **Accurate Image Extraction** — Clicks into each listing's gallery to download ONLY that listing's photos (no similar listings junk)
- 📊 **Multiple Output Formats** — JSON (full data), CSV (summary), and downloaded images organized by listing ID
- ⚡ **Configurable** — Set city, listing count, headless/headed mode
- 🛡️ **Anti-Detection** — Random delays, scroll behavior, and stealth browser settings

## 📋 Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/hassanirshad-1/properties_scraping.git
cd properties_scraping

# Install uv (if you don't have it)
pip install uv

# Install dependencies
uv sync

# Install browser (required for scraping)
uv run playwright install chromium
```

### 2. Run the Scraper

```bash
# Scrape 20 listings from Cairo (with browser visible)
uv run python -m src.cli full --source dubizzle --city cairo --limit 20 --headed

# Scrape 100 listings (headless - faster)
uv run python -m src.cli full --source dubizzle --city cairo --limit 100

# Just scrape data without downloading images
uv run python -m src.cli scrape --source dubizzle --city cairo --limit 50

# Just download images from existing listings.json
uv run python -m src.cli download
```

### 3. View Output

All output is saved to the `output/` directory:

```
output/
├── listings.json          # Full listing data (all fields + image URLs)
├── listings_summary.csv   # Summary table (price, beds, area, location)
├── stats.json             # Scrape statistics
└── images/                # Downloaded images organized by listing ID
    ├── 503425644/
    │   ├── 1.jpeg
    │   ├── 2.jpeg
    │   └── ...
    └── 503304700/
        ├── 1.jpeg
        └── ...
```

## 📦 Output Data

Each listing in `listings.json` contains:

| Field | Example |
|-------|---------|
| `title` | "Luxury Furnished Apartment for Rent" |
| `price` | 50000.0 |
| `price_currency` | "EGP" |
| `price_period` | "monthly" |
| `property_type` | "apartment" |
| `bedrooms` | 3 |
| `bathrooms` | 2 |
| `area_sqm` | 182.0 |
| `furnished` | true |
| `location_city` | "Cairo" |
| `location_area` | "New Cairo" |
| `location_compound` | "Rehab City" |
| `description` | "Full property description..." |
| `features` | ["Balcony", "Pool", "Security", ...] |
| `image_urls` | [list of image URLs] |
| `local_images` | [list of downloaded image paths] |

## ⚙️ CLI Options

```
Usage: python -m src.cli [OPTIONS] COMMAND

Commands:
  scrape    - Scrape listing data only
  download  - Download images from existing listings.json
  full      - Full pipeline: scrape + download images

Options:
  --source    Source website (default: dubizzle)
  --city      City to scrape (default: cairo)
  --limit     Max number of listings (default: 10)
  --headed    Show browser window (useful for debugging)
  -v          Verbose logging
```

## 🏗️ Project Structure

```
src/
├── cli.py              # CLI entry point
├── config.py           # URLs and settings
├── models.py           # PropertyListing data model
├── scraper/
│   ├── base.py         # Base scraper (browser, HTTP, shared logic)
│   └── dubizzle.py     # Dubizzle.com.eg scraper
├── downloader.py       # Image downloader
└── writer.py           # JSON/CSV output writer
```

## 📝 Notes

- The scraper uses Playwright with Chromium for browser automation
- Each listing takes ~5-8 seconds (page load + gallery extraction + delay)
- 300 listings ≈ 30-45 minutes
- Images are downloaded at their original resolution
- The tool respects rate limits with random delays between requests
