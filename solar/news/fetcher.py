"""Fetch recent Indian solar/renewable news and official government notices."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx
from bs4 import BeautifulSoup

from solar.config import DEFAULT_COMPANIES, IST, Company

log = logging.getLogger(__name__)
TIMEOUT = 20

NEWS_QUERIES = [
    "India solar energy industry",
    "India solar module manufacturing",
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


async def _fetch(
    query: str,
    category: str,
    topic_name: str = "",
) -> list[dict]:
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
                "topic_name": topic_name,
            })
        return rows
    except Exception as e:  # noqa: BLE001
        log.warning(f"news fetch failed ({query}): {e}")
        return []


def _company_queries(companies: list[Company]) -> list[str]:
    names = [
        f'"{company.name}"'
        for company in companies
        if company.active
    ]
    return [
        " OR ".join(names[index:index + 6])
        for index in range(0, len(names), 6)
        if names[index:index + 6]
    ]


async def fetch_solar_news(
    companies: list[Company] | None = None,
    supplementary_topics: list[dict] | None = None,
) -> dict:
    """Fetch and strictly prioritize last-24-hour news.

    Older stories are retained only as current-event context and are visibly labelled.
    """
    source = companies if companies is not None else DEFAULT_COMPANIES
    tasks = [_fetch(q, "industry") for q in NEWS_QUERIES + _company_queries(source)]
    tasks += [_fetch(q, "government") for q in GOVT_QUERIES]
    for topic in supplementary_topics or []:
        tasks.append(
            _fetch(topic["query"], "supplementary", topic["name"])
        )
    groups = await asyncio.gather(*tasks)

    core_seen, supplementary_seen = set(), set()
    industry, government, supplementary = [], [], []
    now = datetime.now(IST)
    cutoff = now - timedelta(hours=24)
    fallback_cutoff = now - timedelta(days=7)

    for rows in groups:
        for a in rows:
            key = a["url"] or a["title"].lower()
            seen = (
                supplementary_seen
                if a["category"] == "supplementary"
                else core_seen
            )
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
            if a["category"] == "government":
                government.append(a)
            elif a["category"] == "supplementary":
                supplementary.append(a)
            else:
                industry.append(a)

    def sort_key(a):
        return a["published"] or fallback_cutoff

    industry.sort(key=sort_key, reverse=True)
    government.sort(key=sort_key, reverse=True)
    supplementary.sort(key=sort_key, reverse=True)
    return {
        "industry": industry,
        "government": government,
        "supplementary": supplementary,
        "cutoff": cutoff,
    }
