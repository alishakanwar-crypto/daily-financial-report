"""Collect data, create charts, render the green-themed Solar Industry PDF."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, Undefined
from weasyprint import HTML

from solar.config import COMPANIES, IST, settings
from solar.data.prices import fetch_prices
from solar.data.ratios import fetch_and_store_ratios
from solar.database import mark_articles_sent, ratio_history
from solar.news.ai_analyst import analyze_articles
from solar.news.fetcher import fetch_solar_news

log = logging.getLogger(__name__)
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def fmt_number(value, decimals=2):
    if value is None or isinstance(value, Undefined):
        return "N/A"
    try:
        return f"{value:,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_money(value, currency="INR"):
    if value is None or isinstance(value, Undefined):
        return "N/A"
    symbol = "₹" if currency == "INR" else "$"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e12:
        return f"{sign}{symbol}{value / 1e12:.2f} tn"
    if value >= 1e9:
        return f"{sign}{symbol}{value / 1e9:.2f} bn"
    if value >= 1e7 and currency == "INR":
        return f"{sign}{symbol}{value / 1e7:.2f} cr"
    if value >= 1e6:
        return f"{sign}{symbol}{value / 1e6:.2f} mn"
    return f"{sign}{symbol}{value:,.0f}"


def fmt_money_dual(value, currency="INR", usd_inr_rate=None):
    primary = fmt_money(value, currency)
    if (
        primary == "N/A"
        or currency != "USD"
        or usd_inr_rate is None
        or isinstance(usd_inr_rate, Undefined)
    ):
        return primary
    try:
        return f"{primary} / {fmt_money(value * usd_inr_rate, 'INR')}"
    except (TypeError, ValueError):
        return primary


def pct_class(value):
    if value is None or isinstance(value, Undefined):
        return "neutral"
    try:
        return "positive" if value >= 0 else "negative"
    except TypeError:
        return "neutral"


def impact_class(value):
    return {"positive": "positive", "negative": "negative", "mixed": "mixed"}.get(value, "neutral")


def _best_worst(rows: list[dict], metric: str, higher_is_better=True) -> dict:
    available = [r for r in rows if r.get(metric) is not None and not r.get("unlisted")]
    if not available:
        return {}
    ordered = sorted(available, key=lambda r: r[metric], reverse=higher_is_better)
    return {"best": ordered[0]["name"], "best_value": ordered[0][metric],
            "worst": ordered[-1]["name"], "worst_value": ordered[-1][metric]}


async def collect_report_data() -> dict:
    now = datetime.now(IST)
    # yfinance is synchronous, run price work off the event loop while news downloads.
    price_task = asyncio.to_thread(fetch_prices)
    news_task = fetch_solar_news()
    prices, raw_news = await asyncio.gather(price_task, news_task)
    ratios = await fetch_and_store_ratios()

    industry_task = analyze_articles(raw_news["industry"], "industry news", 7)
    govt_task = analyze_articles(raw_news["government"], "government / regulatory notifications", 6)
    industry, government = await asyncio.gather(industry_task, govt_task)
    await mark_articles_sent(industry["articles"], "industry")
    await mark_articles_sent(government["articles"], "government")

    histories = {}
    for row in ratios:
        if row.get("ticker"):
            histories[row["ticker"]] = await ratio_history(row["ticker"])

    report_date_iso = now.strftime("%Y-%m-%d")
    feedback_url = f"{settings.base_url}/solar/feedback?{urlencode({'report_date': report_date_iso})}"
    listed_ratios = [r for r in ratios if not r.get("unlisted") and not r.get("error")]
    insights = {
        "roe": _best_worst(listed_ratios, "roe"),
        "net_margin": _best_worst(listed_ratios, "net_margin"),
        "revenue_growth": _best_worst(listed_ratios, "revenue_growth"),
        "debt_to_equity": _best_worst(listed_ratios, "debt_to_equity", higher_is_better=False),
        "current_ratio": _best_worst(listed_ratios, "current_ratio"),
        "pe": _best_worst(listed_ratios, "pe", higher_is_better=False),
    }

    return {
        "report_date": now.strftime("%A, %d %B %Y"),
        "report_date_iso": report_date_iso,
        "generated_at": now.strftime("%d-%m-%Y %H:%M:%S IST"),
        "companies": COMPANIES,
        "prices": prices,
        "ratios": ratios,
        "histories": histories,
        "industry": industry,
        "government": government,
        "insights": insights,
        "feedback_url": feedback_url,
    }


async def generate_pdf(output_path: str | None = None) -> tuple[str, dict]:
    data = await collect_report_data()
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters.update({
        "num": fmt_number,
        "money": fmt_money,
        "money_dual": fmt_money_dual,
        "pct_class": pct_class,
        "impact_class": impact_class,
    })
    html = env.get_template("report.html").render(**data)

    report_dir = "data/solar_reports"
    os.makedirs(report_dir, exist_ok=True)
    if output_path is None:
        output_path = os.path.join(report_dir, f"solar_industry_report_{data['report_date_iso']}.pdf")
    HTML(string=html, base_url=os.getcwd()).write_pdf(output_path)
    log.info(f"Solar Industry Report generated: {output_path}")
    return output_path, data
