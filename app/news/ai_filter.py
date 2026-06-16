"""AI-powered article filtering, ranking, and summarization using OpenAI."""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.database import is_article_sent

log = logging.getLogger(__name__)

# Tier-1 sources that should be prioritized
TIER1_SOURCES = {
    "Wall Street Journal", "WSJ", "Bloomberg", "Financial Times", "FT",
    "Reuters", "CNBC", "Barron's", "MarketWatch",
    "Economic Times", "Moneycontrol", "LiveMint", "Business Standard",
    "BBC", "The Guardian",
}

SYSTEM_PROMPT = """You are a senior financial analyst and editor for a premium daily market intelligence brief.
Your job is to select the BEST articles from a pool of candidates based on strict criteria.

SELECTION CRITERIA (in priority order):
1. **Market Impact**: Articles that directly affect stock prices, interest rates, or commodity markets
2. **Source Quality**: STRONGLY prefer articles from top-tier outlets (WSJ, Bloomberg, FT, Reuters, Economic Times, Moneycontrol, CNBC, BBC). Avoid low-quality or niche blogs.
3. **Relevance to Investors**: Information an active investor needs to make decisions TODAY
4. **Depth & Quality**: Prefer in-depth analysis over superficial headlines; prefer primary reporting over aggregation
5. **Readership Trends**: Articles likely to be widely discussed in financial circles
6. **Predictive Value**: News that helps forecast future market movements
7. **Diversity**: Ensure coverage across different sectors (tech, finance, energy, healthcare, etc.)

EXCLUSION CRITERIA:
- Clickbait or sensationalist headlines
- Purely opinion pieces without data backing
- Duplicate stories (same event, different source – pick the BEST source)
- Celebrity/entertainment news even if tangentially financial
- Articles older than 48 hours
- Low-quality or unknown news sources when better alternatives exist

You MUST respond with valid JSON only."""

RANKING_PROMPT_TEMPLATE = """Below are {count} candidate articles for the **{segment}** segment of a daily financial report.

Select exactly **{pick}** articles + **{extra}** "out-of-the-box" article(s) that a sophisticated investor would find valuable.
The out-of-the-box article should be surprising, contrarian, or from an unusual angle that adds perspective.

IMPORTANT: Prefer articles from well-known, reputable financial sources (marked with ★ below).

For each selected article, provide:
- index (0-based from the list below)
- relevance_score (0-100)
- one_line_reason (why this article matters for investors, ≤25 words)
- is_out_of_box (true/false)

Also provide:
- segment_summary: A 3-4 sentence executive summary of what's happening in {segment} markets today. Include key data points, moving trends, and what's driving markets. Write it as a professional market brief.
- market_outlook: 1-2 sentences on what to watch for in the next 24-48 hours. Be specific about potential catalysts.

Candidate articles:
{articles_json}

Respond with this exact JSON structure:
{{
  "selected": [
    {{"index": 0, "relevance_score": 95, "one_line_reason": "...", "is_out_of_box": false}},
    ...
  ],
  "segment_summary": "...",
  "market_outlook": "..."
}}"""


def _is_tier1(source: str) -> bool:
    """Check if a source is tier-1."""
    source_lower = source.lower()
    return any(t.lower() in source_lower for t in TIER1_SOURCES)


async def filter_and_rank(
    articles: list[dict],
    segment: str,
    pick: int = 5,
    extra: int = 1,
) -> dict:
    """Use AI to select the best articles and generate summaries.

    Returns:
        {
            "articles": [...selected articles with ai metadata...],
            "summary": str,
            "outlook": str,
        }
    """
    # Filter out previously sent articles (runs for both AI and fallback paths)
    fresh: list[dict] = []
    for a in articles:
        if not await is_article_sent(a["url"]):
            fresh.append(a)

    if not settings.openai_api_key:
        log.warning("No OpenAI key – falling back to recency-based selection")
        return _fallback_select(fresh, pick + extra, segment)

    if len(fresh) < pick + extra:
        log.warning(f"Only {len(fresh)} fresh articles for {segment}")
        pick = max(1, len(fresh) - extra)
        if len(fresh) == 0:
            return {"articles": [], "summary": "No new articles available.", "outlook": ""}

    # Prepare condensed article list for the prompt
    candidates = []
    for i, a in enumerate(fresh[:60]):  # cap at 60 to stay within context
        source = a.get("feed_name", a.get("source", ""))
        tier_marker = " ★" if _is_tier1(source) else ""
        candidates.append({
            "i": i,
            "title": a["title"],
            "source": f"{source}{tier_marker}",
            "summary": (a.get("summary", "") or "")[:200],
            "url": a["url"],
        })

    prompt = RANKING_PROMPT_TEMPLATE.format(
        count=len(candidates),
        segment=segment.replace("_", " ").title(),
        pick=pick,
        extra=extra,
        articles_json=json.dumps(candidates, indent=2),
    )

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
            timeout=60,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)

        selected_articles = []
        for sel in data.get("selected", []):
            idx = sel["index"]
            if 0 <= idx < len(fresh):
                art = {**fresh[idx]}
                art["relevance_score"] = sel.get("relevance_score", 0)
                art["one_line_reason"] = sel.get("one_line_reason", "")
                art["is_out_of_box"] = sel.get("is_out_of_box", False)
                selected_articles.append(art)

        summary = data.get("segment_summary", "")
        outlook = data.get("market_outlook", "")

        if not summary:
            summary = f"AI analysis of {len(selected_articles)} curated articles for {segment} markets."

        return {
            "articles": selected_articles,
            "summary": summary,
            "outlook": outlook,
        }

    except Exception as e:
        log.error(f"AI filtering failed for {segment}: {e}")
        return _fallback_select(fresh, pick + extra, segment)


def _fallback_select(articles: list[dict], n: int, segment: str) -> dict:
    """Recency-based fallback with source-quality weighting when AI is unavailable."""
    # Sort by tier-1 first, then recency
    tier1 = [a for a in articles if _is_tier1(a.get("feed_name", a.get("source", "")))]
    tier2 = [a for a in articles if not _is_tier1(a.get("feed_name", a.get("source", "")))]

    selected = (tier1 + tier2)[:n]
    for a in selected:
        a["relevance_score"] = 0
        a["one_line_reason"] = ""
        a["is_out_of_box"] = False

    segment_label = segment.replace("_", " ").title()
    return {
        "articles": selected,
        "summary": f"Today's top {len(selected)} financial articles curated from leading {segment_label} sources." if not selected else f"Today's top {len(selected)} financial articles curated from leading {segment_label} sources including {', '.join(set(a.get('feed_name', 'various') for a in selected[:3]))}.",
        "outlook": "Check back tomorrow for AI-powered market analysis and outlook.",
    }
