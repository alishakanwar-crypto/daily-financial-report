"""Fetch financial news from RSS feeds and web sources."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# RSS feeds grouped by segment
FEEDS = {
    "us": [
        ("Wall Street Journal – Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
        ("Reuters – Business", "https://www.rss.reuters.com/news/businessNews"),
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
        ("Financial Times", "https://www.ft.com/rss/home"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ],
    "indian": [
        ("Economic Times – Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
        ("LiveMint", "https://www.livemint.com/rss/markets"),
        ("Business Standard", "https://www.business-standard.com/rss/markets-104.rss"),
        ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
        ("Hindu BusinessLine", "https://www.thehindubusinessline.com/markets/?service=rss"),
    ],
    "international": [
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("Reuters – World", "https://www.rss.reuters.com/news/worldNews"),
        ("Al Jazeera Economy", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian – Business", "https://www.theguardian.com/uk/business/rss"),
        ("DW Business", "https://rss.dw.com/xml/rss-en-bus"),
        ("Nikkei Asia", "https://asia.nikkei.com/rss"),
    ],
}

TIMEOUT = 15  # seconds per feed


async def _fetch_feed(url: str) -> list[dict]:
    """Download and parse a single RSS feed."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "DailyMarketPulse/1.0"})
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries[:30]:  # cap per feed
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6])

            articles.append({
                "title": entry.get("title", "").strip(),
                "url": entry.get("link", "").strip(),
                "summary": _clean_html(entry.get("summary", "")),
                "source": feed.feed.get("title", ""),
                "published": published,
            })
        return articles
    except Exception as e:
        log.warning(f"Feed fetch failed ({url}): {e}")
        return []


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text[:500]  # truncate for context


async def fetch_news_for_segment(segment: str) -> list[dict]:
    """Fetch all articles for a segment (us / indian / international)."""
    feeds = FEEDS.get(segment, [])
    all_articles: list[dict] = []
    for name, url in feeds:
        arts = await _fetch_feed(url)
        for a in arts:
            a["feed_name"] = name
            a["segment"] = segment
        all_articles.extend(arts)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        if a["url"] and a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    # Sort by recency
    now = datetime.utcnow()
    unique.sort(
        key=lambda a: a.get("published") or (now - timedelta(days=30)),
        reverse=True,
    )
    return unique
