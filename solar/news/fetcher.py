"""Fetch recent Indian solar/renewable news and official government notices."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx
from bs4 import BeautifulSoup

from solar.config import IST

log = logging.getLogger(__name__)
TIMEOUT = 20

NEWS_QUERIES = [
    "India solar energy industry",
    "India solar module manufacturing",
    "ReNew Energy OR Waaree OR Premier Energies OR Vikram Solar OR Emmvee",
    "India renewable energy stocks",
    "India solar PLI ALMM DCR",
]
GOVT_QUERIES = [
    "site:mnre.gov.in solar notification",
    "site:pib.gov.in solar renewable energy India",
    "site:sebi.gov.in renewable energy",
    "site:cea.nic.in solar notification",
    "site:powermin.gov.in renewable energy notification",
    "India solar customs duty GST government notification",
]


def _google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def _clean(raw: str) -> str:
    return BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)[:700]


def _published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(IST)


async def _fetch(query: str, category: str) -> list[dict]:
    url = _google_news_rss(query)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "SolarIndustryReport/1.0"})
            response.raise_for_status()
        feed = feedparser.parse(response.text)
        rows = []
        for e in feed.entries[:25]:
            source = ""
            if getattr(e, "source", None):
                source = e.source.get("title", "")
            rows.append({
                "title": e.get("title", "").strip(),
                "url": e.get("link", "").strip(),
                "summary": _clean(e.get("summary", "")),
                "source": source or feed.feed.get("title", "Google News"),
                "published": _published(e),
                "category": category,
                "query": query,
            })
        return rows
    except Exception as e:  # noqa: BLE001
        log.warning(f"news fetch failed ({query}): {e}")
        return []


async def fetch_solar_news() -> dict:
    """Fetch and strictly prioritize last-24-hour news.

    Older stories are retained only as current-event context and are visibly labelled.
    """
    tasks = [_fetch(q, "industry") for q in NEWS_QUERIES]
    tasks += [_fetch(q, "government") for q in GOVT_QUERIES]
    groups = await asyncio.gather(*tasks)

    seen, industry, government = set(), [], []
    now = datetime.now(IST)
    cutoff = now - timedelta(hours=24)
    fallback_cutoff = now - timedelta(days=7)

    for rows in groups:
        for a in rows:
            key = a["url"] or a["title"].lower()
            if not key or key in seen:
                continue
            seen.add(key)
            pub = a["published"]
            if pub and pub >= cutoff:
                a["recency"] = "Last 24 hours"
                a["hours_old"] = round((now - pub).total_seconds() / 3600, 1)
            elif pub and pub >= fallback_cutoff:
                a["recency"] = "Current event context"
                a["hours_old"] = round((now - pub).total_seconds() / 3600, 1)
            else:
                continue
            (government if a["category"] == "government" else industry).append(a)

    def sort_key(a):
        return a["published"] or fallback_cutoff

    industry.sort(key=sort_key, reverse=True)
    government.sort(key=sort_key, reverse=True)
    return {"industry": industry, "government": government, "cutoff": cutoff}
