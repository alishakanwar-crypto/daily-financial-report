"""AI-powered article filtering, ranking, and summarization using OpenAI."""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.database import is_article_sent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior financial analyst and editor for a daily market intelligence brief.
Your job is to select the BEST articles from a pool of candidates based on strict criteria.

SELECTION CRITERIA (in priority order):
1. **Market Impact**: Articles that directly affect stock prices, interest rates, or commodity markets
2. **Relevance to Investors**: Information an active investor needs to make decisions TODAY
3. **Depth & Quality**: Prefer in-depth analysis over superficial news; prefer primary reporting over aggregation
4. **Readership Trends**: Articles likely to be widely discussed in financial circles
5. **Predictive Value**: News that helps forecast future market movements
6. **Diversity**: Ensure coverage across different sectors (tech, finance, energy, healthcare, etc.)

EXCLUSION CRITERIA:
- Clickbait or sensationalist headlines
- Purely opinion pieces without data backing
- Duplicate stories (same event, different source – pick the best one)
- Celebrity/entertainment news even if tangentially financial
- Articles older than 48 hours

You MUST respond with valid JSON only."""

RANKING_PROMPT_TEMPLATE = """Below are {count} candidate articles for the **{segment}** segment of a daily financial report.

Select exactly **{pick}** articles + **{extra}** "out-of-the-box" article(s) that a sophisticated investor would find valuable.
The out-of-the-box article should be surprising, contrarian, or from an unusual angle that adds perspective.

For each selected article, provide:
- index (0-based from the list below)
- relevance_score (0-100)
- one_line_reason (why this article matters, ≤20 words)
- is_out_of_box (true/false)

Candidate articles:
{articles_json}

Respond with this exact JSON structure:
{{
  "selected": [
    {{"index": 0, "relevance_score": 95, "one_line_reason": "...", "is_out_of_box": false}},
    ...
  ],
  "segment_summary": "A 2-3 sentence summary of what's happening in this segment today, with forward-looking expectations.",
  "market_outlook": "One sentence on what to watch for tomorrow."
}}"""


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
        candidates.append({
            "i": i,
            "title": a["title"],
            "source": a.get("feed_name", a.get("source", "")),
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

        return {
            "articles": selected_articles,
            "summary": data.get("segment_summary", ""),
            "outlook": data.get("market_outlook", ""),
        }

    except Exception as e:
        log.error(f"AI filtering failed for {segment}: {e}")
        return _fallback_select(fresh, pick + extra, segment)


def _fallback_select(articles: list[dict], n: int, segment: str) -> dict:
    """Simple recency-based fallback when AI is unavailable."""
    selected = articles[:n]
    for a in selected:
        a["relevance_score"] = 0
        a["one_line_reason"] = ""
        a["is_out_of_box"] = False
    return {
        "articles": selected,
        "summary": f"Top {len(selected)} recent articles for {segment}.",
        "outlook": "",
    }
