"""Fetch recent Indian solar/renewable news and official government notices."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

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

INDIA_SIGNALS = {
    "india",
    "indian",
    "mnre",
    "pib",
    "sebi",
    "bse",
    "nse",
    "new delhi",
    "ministry of new and renewable energy",
    "ministry of power",
}
SOLAR_SIGNALS = {
    "solar",
    "photovoltaic",
    "pv module",
    "pv cell",
    "renewable energy",
    "clean energy",
}
COMMERCIAL_SIGNALS = {
    "policy",
    "notification",
    "guideline",
    "order",
    "tender",
    "capacity",
    "manufacturing",
    "factory",
    "plant",
    "tariff",
    "customs",
    "duty",
    "gst",
    "almm",
    "dcr",
    "pli",
    "supply chain",
    "financing",
    "loan",
    "investment",
    "acquisition",
    "earnings",
    "revenue",
    "margin",
    "module price",
    "cell price",
    "import",
    "export",
    "auction",
    "project",
    "ppa",
}
GENERIC_REJECTION_SIGNALS = {
    "world environment day",
    "how to save electricity",
    "tips for",
    "horoscope",
    "celebrity",
    "lifestyle",
    "green living",
    "esg ranking",
    "opinion: why sustainability",
}
OVERSEAS_SIGNALS = {
    "united states",
    "u.s.",
    "europe",
    "china",
    "australia",
    "canada",
    "africa",
    "middle east",
}
PRIMARY_SOURCE_SIGNALS = {
    "press information bureau",
    "pib",
    "mnre",
    "ministry of power",
    "sebi",
    "bse",
    "nse",
    "renew",
    "waaree",
    "premier energies",
    "vikram solar",
    "emmvee",
}
MIN_RELEVANCE_SCORE = 70


def _google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def _clean(raw: str) -> str:
    return BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)[:700]


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gclid", "fbclid", "oc"}
    ]
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        urlencode(filtered_query),
        "",
    ))


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _signals(text: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in text)


def qualify_article(
    article: dict,
    companies: list[Company],
    now: datetime,
) -> dict | None:
    """Return a deterministically qualified article or ``None``."""
    text = " ".join([
        article.get("title", ""),
        article.get("summary", ""),
        article.get("source", ""),
    ]).lower()
    company_matches = [
        company.name
        for company in companies
        if company.active
        and (
            company.name.lower() in text
            or company.name.lower().replace(" energies", "") in text
            or company.name.lower().replace(" solar", "") in text
        )
    ]
    india_matches = _signals(text, INDIA_SIGNALS)
    solar_matches = _signals(text, SOLAR_SIGNALS)
    commercial_matches = _signals(text, COMMERCIAL_SIGNALS)
    generic_matches = _signals(text, GENERIC_REJECTION_SIGNALS)
    overseas_matches = _signals(text, OVERSEAS_SIGNALS)
    primary_matches = _signals(
        article.get("source", "").lower(),
        PRIMARY_SOURCE_SIGNALS,
    )

    if generic_matches:
        return None
    if not india_matches:
        return None
    if not solar_matches and not company_matches:
        return None
    if not commercial_matches:
        return None
    if overseas_matches and not india_matches:
        return None

    published = article.get("published")
    hours_old = (
        (now - published).total_seconds() / 3600
        if published is not None
        else None
    )
    score = 25
    score += min(20, len(india_matches) * 10)
    score += 20 if solar_matches else 0
    score += min(20, len(commercial_matches) * 5)
    score += 10 if company_matches else 0
    score += 10 if primary_matches else 0
    score += 10 if hours_old is not None and hours_old <= 24 else 0
    score -= 10 if overseas_matches and not company_matches else 0
    score = max(0, min(100, score))
    if score < MIN_RELEVANCE_SCORE:
        return None
    if hours_old is not None and hours_old > 24 and score < 80:
        return None

    evidence = []
    if india_matches:
        evidence.append(f"India: {', '.join(india_matches[:2])}")
    if solar_matches:
        evidence.append(f"solar: {', '.join(solar_matches[:2])}")
    if company_matches:
        evidence.append(f"tracked company: {', '.join(company_matches)}")
    if commercial_matches:
        evidence.append(f"commercial/policy: {', '.join(commercial_matches[:3])}")
    if primary_matches:
        evidence.append("primary/official source signal")
    return {
        **article,
        "url": _canonical_url(article["url"]),
        "deterministic_relevance_score": score,
        "relevance_evidence": evidence,
        "supported_companies": company_matches,
        "primary_source_preferred": bool(primary_matches),
    }


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
    core_titles, supplementary_titles = set(), set()
    industry, government, supplementary = [], [], []
    now = datetime.now(IST)
    cutoff = now - timedelta(hours=24)
    fallback_cutoff = now - timedelta(days=7)

    candidates = [article for rows in groups for article in rows]
    candidates.sort(key=lambda article: article["category"] != "government")
    for a in candidates:
        key = _canonical_url(a["url"]) if a["url"] else ""
        title_key = _normalized_title(a["title"])
        seen = (
            supplementary_seen
            if a["category"] == "supplementary"
            else core_seen
        )
        seen_titles = (
            supplementary_titles
            if a["category"] == "supplementary"
            else core_titles
        )
        if not key or key in seen or not title_key or title_key in seen_titles:
            continue
        seen.add(key)
        seen_titles.add(title_key)
        a["url"] = key
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
            qualified = qualify_article(a, source, now)
            if qualified:
                government.append(qualified)
        elif a["category"] == "supplementary":
            a["deterministic_relevance_score"] = 75
            a["relevance_evidence"] = [
                f"Selected supplementary topic: {a['topic_name']}"
            ]
            a["supported_companies"] = []
            supplementary.append(a)
        else:
            qualified = qualify_article(a, source, now)
            if qualified:
                industry.append(qualified)

    def sort_key(a):
        return a["published"] or fallback_cutoff

    industry.sort(
        key=lambda article: (
            article["deterministic_relevance_score"],
            sort_key(article),
        ),
        reverse=True,
    )
    government.sort(
        key=lambda article: (
            article["deterministic_relevance_score"],
            sort_key(article),
        ),
        reverse=True,
    )
    supplementary.sort(key=sort_key, reverse=True)
    return {
        "industry": industry,
        "government": government,
        "supplementary": supplementary,
        "cutoff": cutoff,
    }
