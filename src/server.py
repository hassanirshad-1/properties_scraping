"""
Bawab Scraper API Server

FastAPI backend that:
1. Exposes endpoints to trigger scraping, view listings, check status
2. Auto-schedules scraping every X hours via APScheduler
3. Runs AI analysis on new listings
4. Syncs results directly into Bawab's Postgres database
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.config import AI_API_KEY, AI_BASE_URL, AI_MODEL

logger = logging.getLogger(__name__)

# ── App Setup ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Bawab Scraper API",
    description="Auto-scrapes Egyptian property listings, analyzes images with AI, and syncs to Bawab database.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── State ───────────────────────────────────────────────────────────────────

class JobStatus:
    def __init__(self):
        self.is_running = False
        self.last_run: str | None = None
        self.last_result: dict | None = None
        self.current_step: str = "idle"
        self.progress: str = ""

job_status = JobStatus()


# ── Request / Response Models ───────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    city: str = "cairo"
    limit: int = 50
    source: str = "dubizzle"
    analyze: bool = True      # Run AI analysis after scraping
    sync_db: bool = True      # Push to Bawab database after analysis

class ScrapeResponse(BaseModel):
    status: str
    message: str

class StatusResponse(BaseModel):
    is_running: bool
    current_step: str
    progress: str
    last_run: str | None
    last_result: dict | None


# ── Background Scrape Job ───────────────────────────────────────────────────

async def run_scrape_job(
    city: str = "cairo",
    limit: int = 50,
    source: str = "dubizzle",
    analyze: bool = True,
    sync_db: bool = True,
):
    """
    The full pipeline: scrape → download images → AI analyze → sync to DB.
    Runs in background.
    """
    global job_status
    job_status.is_running = True
    job_status.current_step = "starting"
    job_status.progress = ""

    try:
        # ── Step 1: Scrape listings ─────────────────────────────────────
        job_status.current_step = "scraping"
        job_status.progress = f"Scraping {source} for {city} (limit={limit})..."
        logger.info("Starting scrape: %s / %s / limit=%d", source, city, limit)

        from src.scraper.dubizzle import DubizzleScraper
        scraper = DubizzleScraper(headed=False)

        try:
            listings = await scraper.scrape_listings(city=city, limit=limit)
        finally:
            await scraper.close()

        job_status.progress = f"Scraped {len(listings)} listings"
        logger.info("Scraped %d listings", len(listings))

        # ── Step 2: Download images ─────────────────────────────────────
        job_status.current_step = "downloading_images"
        job_status.progress = f"Downloading images for {len(listings)} listings..."
        logger.info("Downloading images...")

        from src.images.downloader import download_all_images
        listings = await download_all_images(listings)

        total_images = sum(len(l.local_images) for l in listings)
        job_status.progress = f"Downloaded {total_images} images"
        logger.info("Downloaded %d total images", total_images)

        # ── Step 3: AI Analysis ─────────────────────────────────────────
        if analyze and AI_API_KEY:
            job_status.current_step = "ai_analysis"
            job_status.progress = "Running AI image analysis..."
            logger.info("Starting AI analysis...")

            from src.images.analyzer import analyze_all_listings
            listings = await analyze_all_listings(listings)

            analyzed = sum(1 for l in listings if l.ai_analysis)
            job_status.progress = f"Analyzed {analyzed}/{len(listings)} listings"
            logger.info("AI analysis complete: %d/%d", analyzed, len(listings))
        elif not AI_API_KEY:
            logger.warning("No AI API key set — skipping analysis")

        # ── Step 4: Save JSON output ────────────────────────────────────
        job_status.current_step = "saving"
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        data = [l.to_dict() for l in listings]
        output_file = output_dir / "listings.json"
        output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %d listings to %s", len(data), output_file)

        # ── Step 5: Sync to Bawab DB ───────────────────────────────────
        db_stats = None
        if sync_db:
            db_url = os.environ.get("DATABASE_URL")
            if db_url:
                job_status.current_step = "syncing_database"
                job_status.progress = f"Syncing {len(listings)} listings to Bawab DB..."
                logger.info("Syncing to Bawab database...")

                from src.db_sync import BawabSyncService
                sync = BawabSyncService(db_url)
                try:
                    db_stats = await sync.sync_listings(listings)
                    job_status.progress = f"Synced: {db_stats}"
                finally:
                    await sync.close()
            else:
                logger.warning("No DATABASE_URL set — skipping DB sync")

        # ── Done ────────────────────────────────────────────────────────
        result = {
            "listings_scraped": len(listings),
            "images_downloaded": total_images,
            "ai_analyzed": sum(1 for l in listings if l.ai_analysis),
            "db_sync": db_stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        job_status.current_step = "done"
        job_status.progress = f"Complete: {len(listings)} listings"
        job_status.last_result = result
        job_status.last_run = datetime.now(timezone.utc).isoformat()
        logger.info("Pipeline complete: %s", result)

    except Exception as e:
        logger.exception("Scrape job failed: %s", e)
        job_status.current_step = f"error: {str(e)[:100]}"
        job_status.last_result = {"error": str(e)}
    finally:
        job_status.is_running = False


# ── API Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "Bawab Scraper API", "version": "1.0.0", "status": "running"}


@app.post("/api/scrape", response_model=ScrapeResponse)
async def trigger_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    """Trigger a new scrape job in the background."""
    if job_status.is_running:
        raise HTTPException(status_code=409, detail="A scrape job is already running")

    background_tasks.add_task(
        run_scrape_job,
        city=req.city,
        limit=req.limit,
        source=req.source,
        analyze=req.analyze,
        sync_db=req.sync_db,
    )

    return ScrapeResponse(
        status="started",
        message=f"Scraping {req.source}/{req.city} (limit={req.limit}) in background",
    )


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Check the current scrape job status."""
    return StatusResponse(
        is_running=job_status.is_running,
        current_step=job_status.current_step,
        progress=job_status.progress,
        last_run=job_status.last_run,
        last_result=job_status.last_result,
    )


@app.get("/api/listings")
async def get_listings(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """Get scraped listings from the local JSON output."""
    output_file = Path("output/listings.json")
    if not output_file.exists():
        return {"listings": [], "total": 0, "page": page, "limit": limit}

    data = json.loads(output_file.read_text(encoding="utf-8"))
    total = len(data)
    start = (page - 1) * limit
    end = start + limit

    return {
        "listings": data[start:end],
        "total": total,
        "page": page,
        "limit": limit,
    }


@app.get("/api/search")
async def smart_search(q: str = Query(..., description="Natural language search query")):
    """
    Smart search: match a natural language query against AI-analyzed listings.
    Example: 'modern furnished apartment with balcony and garden view'
    """
    output_file = Path("output/listings.json")
    if not output_file.exists():
        return {"query": q, "results": [], "total": 0}

    data = json.loads(output_file.read_text(encoding="utf-8"))
    query_words = q.lower().split()

    results = []
    for listing in data:
        ai = listing.get("ai_analysis")
        if not ai:
            continue

        # Build searchable text from AI analysis
        tags = [t.lower() for t in ai.get("search_tags", [])]
        features = [f.lower() for f in ai.get("notable_features", [])]
        vibe = ai.get("overall_vibe", "").lower()
        view = str(ai.get("view_type", "")).lower()
        floor = str(ai.get("estimated_floor", "")).lower()
        quality = str(ai.get("interior_quality", "")).lower()
        furniture = str(ai.get("furniture_style", "")).lower()

        all_text = " ".join(tags + features + [vibe, view, floor, quality, furniture])

        # Score: how many query words appear in the searchable text
        matches = sum(1 for w in query_words if w in all_text)
        score = matches / len(query_words) if query_words else 0

        if score >= 0.3:  # At least 30% match
            results.append({
                "listing": listing,
                "score": round(score, 2),
                "matched_tags": [t for t in tags if any(w in t for w in query_words)],
            })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": q,
        "results": results[:20],
        "total": len(results),
    }


# ── Scheduler ───────────────────────────────────────────────────────────────

def setup_scheduler():
    """Set up APScheduler to auto-scrape every N hours."""
    interval_hours = int(os.environ.get("SCRAPE_INTERVAL_HOURS", "6"))
    scrape_city = os.environ.get("SCRAPE_CITY", "cairo")
    scrape_limit = int(os.environ.get("SCRAPE_LIMIT", "100"))

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()

    async def scheduled_scrape():
        if job_status.is_running:
            logger.info("Scheduled scrape skipped — job already running")
            return
        logger.info("Scheduled scrape starting: %s/%s limit=%d", "dubizzle", scrape_city, scrape_limit)
        await run_scrape_job(city=scrape_city, limit=scrape_limit)

    scheduler.add_job(
        scheduled_scrape,
        "interval",
        hours=interval_hours,
        id="auto_scrape",
        name=f"Auto-scrape {scrape_city} every {interval_hours}h",
    )
    scheduler.start()
    logger.info("Scheduler started: scraping every %d hours", interval_hours)
    return scheduler


@app.on_event("startup")
async def startup():
    """Run on server startup."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Install Playwright browser if not already installed
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
            logger.info("Playwright browser verified")
    except Exception as e:
        logger.warning("Playwright browser check failed: %s (run: playwright install chromium)", e)

    # Start the auto-scheduler
    if os.environ.get("ENABLE_SCHEDULER", "true").lower() == "true":
        setup_scheduler()
    else:
        logger.info("Scheduler disabled (set ENABLE_SCHEDULER=true to enable)")


# ── CLI Entry Point ─────────────────────────────────────────────────────────

def main():
    """Run the server directly: python -m src.server"""
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "src.server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
