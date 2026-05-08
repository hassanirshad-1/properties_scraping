# Bawab Property Scraper & AI Pipeline

Automated property scraping + AI image analysis + database sync for [Bawab](https://bawab.app).

## What It Does

```
Dubizzle.com.eg → Scrape Listings → Download Photos → AI Analyzes Images → Push to Bawab DB
                                                          ↓
                                              search_tags, floor estimate,
                                              view type, sun direction,
                                              interior quality, features
```

**Every 6 hours** (configurable), the system:
1. Scrapes 100+ property listings from Dubizzle Egypt
2. Downloads all gallery photos for each listing
3. Sends photos to AI (Kimi K2.5) for visual analysis
4. Syncs everything into Bawab's Postgres database
5. Enables "smart search" — users type natural language, AI matches against analyzed data

## Quick Start

```bash
# 1. Clone & install
git clone https://github.com/hassanirshad-1/properties_scraping.git
cd properties_scraping
pip install uv
uv sync
uv run playwright install chromium

# 2. Set environment variables (copy .env.example → .env)
cp .env.example .env
# Edit .env with your API keys

# 3. Run the API server (auto-schedules scraping)
uv run python -m src.server
```

The server starts at `http://localhost:8000` and auto-scrapes every 6 hours.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `POST` | `/api/scrape` | Trigger a scrape job |
| `GET` | `/api/status` | Check current job status |
| `GET` | `/api/listings` | Get scraped listings |
| `GET` | `/api/search?q=...` | Smart search |

### Trigger a Scrape
```bash
curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"city": "cairo", "limit": 50, "analyze": true, "sync_db": true}'
```

### Smart Search
```bash
curl "http://localhost:8000/api/search?q=modern+furnished+apartment+with+balcony"
```

## CLI Usage (Manual Scraping)

```bash
# Scrape only
uv run python -m src.cli scrape --source dubizzle --city cairo --limit 20

# Full pipeline (scrape + download images + analyze)
uv run python -m src.cli full --source dubizzle --city cairo --limit 20

# Analyze existing listings
uv run python -m src.cli analyze
```

## Environment Variables

```env
# AI Image Analysis
AGENTROUTER_BASE_URL=https://api.swiftrouter.com/v1/
AGENTROUTER_API_KEY=your-key
AGENTROUTER_MODEL_NAME=kimi-k2.5

# Bawab Database
DATABASE_URL=postgres://user:pass@host:5432/bawab

# Auto-Scheduler
ENABLE_SCHEDULER=true
SCRAPE_INTERVAL_HOURS=6
SCRAPE_CITY=cairo
SCRAPE_LIMIT=100

# Server
PORT=8000
```

## Database Migration

Before first sync, run the migration against Bawab's database:

```bash
psql $DATABASE_URL -f migrations/001_add_ai_search_columns.sql
```

This adds: `source_url`, `source_id`, `ai_tags`, `ai_vibe`, `ai_analysis` columns + GIN indexes for fast tag search.

## Architecture

```
src/
├── server.py          # FastAPI server + scheduler
├── cli.py             # CLI interface
├── config.py          # Configuration
├── db_sync.py         # Bawab database sync service
├── scraper/
│   ├── base.py        # Base scraper (Playwright)
│   ├── dubizzle.py    # Dubizzle.com.eg scraper
│   └── models.py      # PropertyListing data model
└── images/
    ├── downloader.py  # Image download service
    └── analyzer.py    # AI image analysis (Kimi K2.5)

bawab_patches/
└── enhanced_search.ts # Drop-in replacement for Bawab's search route

migrations/
└── 001_add_ai_search_columns.sql
```

## AI Analysis Output

For each listing, the AI returns:
```json
{
  "estimated_floor": "1-2",
  "view_type": "compound",
  "sun_direction": "south",
  "interior_quality": "luxury",
  "furniture_style": "furnished-modern",
  "notable_features": ["balcony", "marble floors", "AC"],
  "search_tags": ["modern apartment", "furnished", "balcony", "natural light"],
  "overall_vibe": "Bright, airy apartment with minimalist beige interiors."
}
```

These tags power the **smart search** — users can type "3rd floor north facing garden view" and get matching results.
