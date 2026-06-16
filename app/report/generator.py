"""Orchestrate data collection and generate the final PDF report."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from jinja2 import Environment, FileSystemLoader

from app.config import settings, IST
from app.data.stocks import fetch_stock_data
from app.data.commodities import fetch_commodities, fetch_indices
from app.data.financials import select_deep_dive
from app.news.fetcher import fetch_news_for_segment
from app.news.ai_filter import filter_and_rank
from app.database import mark_articles_sent

log = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _is_weekend() -> bool:
    return datetime.now(IST).weekday() in (5, 6)  # Sat=5, Sun=6


async def collect_all_data() -> dict:
    """Gather every data point needed for the report."""
    weekend = _is_weekend()

    log.info("Fetching Indian stocks...")
    indian_stocks = fetch_stock_data(settings.indian_stocks, currency="INR")

    log.info("Fetching US stocks...")
    us_stocks = fetch_stock_data(settings.us_stocks, currency="USD")

    log.info("Fetching commodities & indices...")
    commodities = fetch_commodities(is_weekend=weekend)
    indices = fetch_indices(is_weekend=weekend)

    log.info("Fetching deep dive data...")
    deep_dive = select_deep_dive()

    # News
    log.info("Fetching & filtering Indian news...")
    indian_raw = await fetch_news_for_segment("indian")
    indian_news = await filter_and_rank(indian_raw, "indian", pick=5, extra=1)
    await mark_articles_sent(indian_news["articles"], "indian")

    log.info("Fetching & filtering US news...")
    us_raw = await fetch_news_for_segment("us")
    us_news = await filter_and_rank(us_raw, "us", pick=5, extra=1)
    await mark_articles_sent(us_news["articles"], "us")

    log.info("Fetching & filtering International news...")
    intl_raw = await fetch_news_for_segment("international")
    intl_news = await filter_and_rank(intl_raw, "international", pick=5, extra=1)
    await mark_articles_sent(intl_news["articles"], "international")

    now_ist = datetime.now(IST)
    report_date = now_ist.date()
    if weekend:
        # Show last trading day
        days_back = 1 if report_date.weekday() == 5 else 2
        trading_date = report_date - timedelta(days=days_back)
    else:
        trading_date = report_date

    return {
        "report_date": report_date.strftime("%A, %B %d, %Y"),
        "trading_date": trading_date.strftime("%A, %B %d, %Y"),
        "is_weekend": weekend,
        "indian_stocks": indian_stocks,
        "us_stocks": us_stocks,
        "commodities": commodities,
        "indices": indices,
        "deep_dive": deep_dive,
        "indian_news": indian_news,
        "us_news": us_news,
        "intl_news": intl_news,
        "generated_at": now_ist.strftime("%d-%m-%Y %H:%M:%S IST"),
    }


def _fmt(val, decimals=2, prefix="", suffix=""):
    if val is None:
        return "N/A"
    return f"{prefix}{val:,.{decimals}f}{suffix}"


def _change_class(val):
    if val is None:
        return "neutral"
    return "positive" if val >= 0 else "negative"


def _change_arrow(val):
    if val is None:
        return ""
    return "▲" if val >= 0 else "▼"


async def generate_pdf(output_path: str | None = None) -> str:
    """Generate the daily report PDF and return the file path."""
    data = await collect_all_data()

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters["fmt"] = _fmt
    env.filters["change_class"] = _change_class
    env.filters["change_arrow"] = _change_arrow
    env.globals["fmt"] = _fmt
    env.globals["change_class"] = _change_class
    env.globals["change_arrow"] = _change_arrow

    template = env.get_template("report.html")
    html_content = template.render(**data)

    # Generate PDF
    os.makedirs("data/reports", exist_ok=True)
    if output_path is None:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        output_path = f"data/reports/market_pulse_{date_str}.pdf"

    from weasyprint import HTML
    HTML(string=html_content).write_pdf(output_path)

    log.info(f"PDF generated: {output_path}")
    return output_path
