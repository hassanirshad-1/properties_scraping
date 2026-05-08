"""CLI entry point for the property scraper."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Fix Windows console encoding for Unicode
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from src.config import OUTPUT_DIR, DUBIZZLE_RENT_APARTMENTS


console = Console(force_terminal=True)


def setup_logging(verbose: bool = False):
    """Configure logging with rich output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="scrape",
        description="Egypt Property Scraper - Scrape rental listings for bawab.app",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # === scrape command ===
    scrape_cmd = subparsers.add_parser("scrape", help="Scrape property listings")
    scrape_cmd.add_argument(
        "--source", "-s",
        choices=["dubizzle", "bayut", "all"],
        default="dubizzle",
        help="Which site to scrape (default: dubizzle)",
    )
    scrape_cmd.add_argument(
        "--city", "-c",
        default="cairo",
        help=f"City to scrape. Available: {', '.join(DUBIZZLE_RENT_APARTMENTS.keys())}",
    )
    scrape_cmd.add_argument(
        "--limit", "-l",
        type=int,
        default=20,
        help="Max number of listings to scrape (default: 20)",
    )
    scrape_cmd.add_argument(
        "--no-details",
        action="store_true",
        help="Skip scraping detail pages (faster but less data)",
    )
    scrape_cmd.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (visible window, useful for debugging)",
    )
    scrape_cmd.add_argument(
        "--output", "-o",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory (default: ./output)",
    )

    # === download-images command ===
    dl_cmd = subparsers.add_parser("download-images", help="Download images for scraped listings")
    dl_cmd.add_argument(
        "--input", "-i",
        type=Path,
        default=OUTPUT_DIR / "listings.json",
        help="Path to listings.json file",
    )
    dl_cmd.add_argument(
        "--output", "-o",
        type=Path,
        default=OUTPUT_DIR / "images",
        help="Output directory for images",
    )

    # === analyze command ===
    analyze_cmd = subparsers.add_parser("analyze", help="Run AI analysis on downloaded images")
    analyze_cmd.add_argument(
        "--input", "-i",
        type=Path,
        default=OUTPUT_DIR / "listings.json",
        help="Path to listings.json file",
    )
    analyze_cmd.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Gemini API key (or set GEMINI_API_KEY env var)",
    )
    analyze_cmd.add_argument(
        "--output", "-o",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory",
    )

    # === full command ===
    full_cmd = subparsers.add_parser("full", help="Full pipeline: scrape + download images + analyze")
    full_cmd.add_argument(
        "--source", "-s",
        choices=["dubizzle", "bayut", "all"],
        default="dubizzle",
        help="Which site to scrape (default: dubizzle)",
    )
    full_cmd.add_argument(
        "--city", "-c",
        default="cairo",
        help="City to scrape",
    )
    full_cmd.add_argument(
        "--limit", "-l",
        type=int,
        default=20,
        help="Max listings (default: 20)",
    )
    full_cmd.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Gemini API key for AI analysis (optional)",
    )
    full_cmd.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode",
    )
    full_cmd.add_argument(
        "--output", "-o",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory",
    )

    return parser


async def cmd_scrape(args):
    """Execute the scrape command."""
    from src.scraper.dubizzle import DubizzleScraper
    from src.output.writer import save_listings

    console.print(Panel(
        f"[SCRAPER] Scraping [bold cyan]{args.source}[/] -- City: [bold]{args.city}[/] -- Limit: [bold]{args.limit}[/]",
        title="Property Scraper",
        border_style="cyan",
    ))

    listings = []

    if args.source in ("dubizzle", "all"):
        async with DubizzleScraper(headless=not args.headed) as scraper:
            dubizzle_listings = await scraper.scrape_listings(
                city=args.city,
                limit=args.limit,
            )
            listings.extend(dubizzle_listings)

    if not listings:
        console.print("[red]No listings scraped![/red]")
        return

    # Save results
    save_listings(listings, args.output)

    # Display summary
    _print_summary(listings)


async def cmd_download_images(args):
    """Execute the download-images command."""
    from src.output.writer import load_listings, save_listings
    from src.images.downloader import download_images_for_listings

    listings = load_listings(args.input)
    if not listings:
        console.print("[red]No listings found in input file![/red]")
        return

    console.print(f"[IMAGES] Downloading images for [bold]{len(listings)}[/bold] listings...")
    listings = await download_images_for_listings(listings, output_dir=args.output)

    # Re-save with local image paths
    save_listings(listings, args.input.parent)
    console.print(f"[green]>> Images downloaded to {args.output}[/green]")


async def cmd_analyze(args):
    """Execute the analyze command."""
    from src.output.writer import load_listings, save_listings
    from src.images.analyzer import analyze_all_listings

    listings = load_listings(args.input)
    if not listings:
        console.print("[red]No listings found![/red]")
        return

    # Filter to listings with downloaded images
    with_images = [l for l in listings if l.local_images]
    console.print(f"[AI] Analyzing images for [bold]{len(with_images)}[/bold] listings with Gemini Vision...")

    listings = await analyze_all_listings(listings, api_key=args.api_key)

    # Re-save with AI analysis
    save_listings(listings, args.output)

    analyzed = sum(1 for l in listings if l.ai_analysis)
    console.print(f"[green]>> AI analysis complete: {analyzed} listings analyzed[/green]")


async def cmd_full(args):
    """Execute the full pipeline: scrape -> download -> analyze."""
    from src.scraper.dubizzle import DubizzleScraper
    from src.images.downloader import download_images_for_listings
    from src.images.analyzer import analyze_all_listings
    from src.output.writer import save_listings

    console.print(Panel(
        f"[FULL PIPELINE] [bold cyan]{args.source}[/] / [bold]{args.city}[/] / limit={args.limit}",
        title="Property Scraper",
        border_style="green",
    ))

    # Step 1: Scrape
    console.print("\n[bold]Step 1/3:[/bold] Scraping listings...")
    listings = []
    if args.source in ("dubizzle", "all"):
        async with DubizzleScraper(headless=not args.headed) as scraper:
            listings.extend(await scraper.scrape_listings(city=args.city, limit=args.limit))

    if not listings:
        console.print("[red]No listings scraped![/red]")
        return

    save_listings(listings, args.output)
    console.print(f"[green]>> Scraped {len(listings)} listings[/green]\n")

    # Step 2: Download images
    console.print("[bold]Step 2/3:[/bold] Downloading images...")
    listings = await download_images_for_listings(listings)
    save_listings(listings, args.output)
    total_imgs = sum(len(l.local_images) for l in listings)
    console.print(f"[green]>> Downloaded {total_imgs} images[/green]\n")

    # Step 3: AI Analysis (if API key provided)
    if args.api_key:
        console.print("[bold]Step 3/3:[/bold] Running AI image analysis...")
        listings = await analyze_all_listings(listings, api_key=args.api_key)
        save_listings(listings, args.output)
        analyzed = sum(1 for l in listings if l.ai_analysis)
        console.print(f"[green]>> Analyzed {analyzed} listings[/green]\n")
    else:
        console.print("[dim]Step 3/3: Skipped AI analysis (no --api-key provided)[/dim]\n")

    # Final summary
    _print_summary(listings)


def _print_summary(listings):
    """Print a nice summary table of scraped listings."""
    table = Table(title="Scraped Listings Summary", border_style="cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Price", style="green", width=18)
    table.add_column("Beds", width=4)
    table.add_column("Area", width=8)
    table.add_column("Location", style="yellow", width=25)
    table.add_column("Images", width=6)
    table.add_column("AI", width=3)

    for i, l in enumerate(listings[:30], 1):  # Show first 30
        table.add_row(
            str(i),
            l.property_type[:10],
            l.price_display,
            str(l.bedrooms) if l.bedrooms else "-",
            f"{l.area_sqm:.0f}m2" if l.area_sqm else "-",
            (l.location_area or l.location_city)[:25],
            str(len(l.image_urls)),
            "Y" if l.ai_analysis else "-",
        )

    if len(listings) > 30:
        table.add_row("...", f"+{len(listings) - 30} more", "", "", "", "", "", "")

    console.print(table)
    console.print(f"\n[bold green]Total: {len(listings)} listings[/bold green]")
    console.print(f"Output saved to: [cyan]{OUTPUT_DIR}[/cyan]")


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)

    command_map = {
        "scrape": cmd_scrape,
        "download-images": cmd_download_images,
        "analyze": cmd_analyze,
        "full": cmd_full,
    }

    handler = command_map.get(args.command)
    if handler:
        try:
            asyncio.run(handler(args))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            logging.exception("Unhandled error")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
