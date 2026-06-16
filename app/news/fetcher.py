"""Fetch financial news from RSS feeds and web sources."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# RSS feeds grouped by segment — prioritized by source quality
FEEDS = {
    "us": [
        # Tier 1: Premium financial outlets
        ("Wall Street Journal – Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("Wall Street Journal – Business", "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"),
        ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
        ("Financial Times", "https://www.ft.com/rss/home"),
        ("Reuters – Business", "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US"),
        # Tier 2: High quality
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Barron's", "https://feeds.content.dowjones.io/public/rss/barrons_topstories"),
        # Tier 3: Supplementary
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("Investing.com", "https://www.investing.com/rss/news.rss"),
    ],
    "indian": [
        # Tier 1: Top Indian financial sources
        ("Economic Times – Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("Economic Times – Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
        ("LiveMint – Markets", "https://www.livemint.com/rss/markets"),
        ("LiveMint – Economy", "https://www.livemint.com/rss/economy"),
        # Tier 2
        ("Business Standard – Markets", "https://www.business-standard.com/rss/markets-104.rss"),
        ("Business Standard – Economy", "https://www.business-standard.com/rss/economy-102.rss"),
        ("Hindu BusinessLine", "https://www.thehindubusinessline.com/markets/?service=rss"),
        ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
        ("Financial Express", "https://www.financialexpress.com/market/feed/"),
    ],
    "international": [
        # Tier 1: Global coverage
        ("Reuters – World", "https://news.google.com/rss/search?q=site:reuters.com+economy+OR+markets&hl=en-US"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian – Business", "https://www.theguardian.com/uk/business/rss"),
        ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
        # Tier 2
        ("Al Jazeera Economy", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("DW Business", "https://rss.dw.com/xml/rss-en-bus"),
        ("Nikkei Asia", "https://news.google.com/rss/search?q=site:asia.nikkei.com&hl=en-US"),
        ("South China Morning Post – Economy", "https://www.scmp.com/rss/5/feed"),
    ],
}

TIMEOUT = 15  # seconds per feed


async def _fetch_feed(url: str, feed_name: str) -> list[dict]:
    """Download and parse a single RSS feed."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DailyMarketPulse/2.0; +https://github.com)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            })
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries[:30]:  # cap per feed
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6])

            title = entry.get("title", "").strip()
            url_str = entry.get("link", "").strip()
            if not title or not url_str:
                continue

            articles.append({
                "title": title,
                "url": url_str,
                "summary": _clean_html(entry.get("summary", "")),
                "source": feed.feed.get("title", feed_name),
                "published": published,
            })
        return articles
    except Exception as e:
        log.warning(f"Feed fetch failed ({feed_name} / {url}): {e}")
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
        arts = await _fetch_feed(url, name)
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
