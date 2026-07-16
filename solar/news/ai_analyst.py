"""Feedback-aware AI analyst for relevance ranking and investor commentary."""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from solar.config import settings
from solar.database import article_was_sent, feedback_memory

log = logging.getLogger(__name__)

SYSTEM = """You are the competitive-intelligence analyst for an Indian solar technology company.
Your reader is an industry insider, not a general-news reader. Be factual, concise and commercially useful.
Rank news for its impact on Indian solar manufacturers, developers and listed solar stocks.

High priority: government policy (MNRE, PLI, ALMM, DCR, BCD/customs, GST, tenders), capacity
expansions, order wins, prices/margins, technology, supply chains, Chinese competition,
financing and actions involving the currently tracked competitive set: {companies}.
Exclude generic ESG stories, overseas-only solar stories without Indian impact, PR fluff and duplicates.
Prefer stories from the last 24 hours. Older items may only be selected when they concern a still-active
event affecting the industry; clearly label them current-event context.

The editor feedback below is durable preference memory. Apply it when selecting and writing.
--- EDITOR FEEDBACK MEMORY ---
{feedback}
--- END FEEDBACK ---

Return valid JSON only. Never invent facts or URLs."""

PROMPT = """Select up to {count} of the most decision-useful {category} items from these candidates.
For each selection return: index, impact_score (0-100), impact (positive/negative/mixed/neutral),
one_line_why (max 25 words), companies_affected (array), and investor_takeaway (max 35 words).
Also provide a 3-sentence executive_summary and 3 watch_items.
Candidates:
{candidates}
Response: {{"selected": [...], "executive_summary": "...", "watch_items": ["...", "...", "..."]}}"""

SUPPLEMENTARY_SYSTEM = """You curate a separate supplementary intelligence section for an Indian solar industry operator.
Only select stories that match the editor's chosen topics. These stories need not be about solar directly.
Explain implications for energy prices, shipping, commodities, supply chains, financing, Indian markets or business risk.
Do not mix these stories into the core solar or government sections.

The editor feedback below is durable preference memory. Apply it when selecting and writing.
--- EDITOR FEEDBACK MEMORY ---
{feedback}
--- END FEEDBACK ---

Return valid JSON only. Never invent facts, links or implications."""

SUPPLEMENTARY_PROMPT = """The editor selected these supplementary topics: {topics}.
Select up to {count} current stories from the candidates.
For each selection return: index, impact_score (0-100), impact
(positive/negative/mixed/neutral), one_line_why (max 30 words),
companies_affected (array), and investor_takeaway (max 40 words).
Also provide a 3-sentence executive_summary and 3 watch_items.
Candidates:
{candidates}
Response: {{"selected": [...], "executive_summary": "...", "watch_items": ["...", "...", "..."]}}"""


def _fallback(articles: list[dict], count: int) -> dict:
    selected = articles[:count]
    for a in selected:
        a.update({
            "impact_score": 50,
            "impact": "neutral",
            "one_line_why": "Recent development relevant to the Indian solar industry.",
            "companies_affected": [],
            "investor_takeaway": "Review the linked source for implications.",
        })
    return {"articles": selected, "executive_summary": "AI analysis unavailable; showing the most recent relevant items.", "watch_items": []}


async def analyze_articles(
    articles: list[dict],
    category: str,
    count: int,
    company_names: list[str] | None = None,
) -> dict:
    fresh = []
    for article in articles:
        # Allow current official government context to recur; de-duplicate ordinary news.
        if category == "government" or not await article_was_sent(article["url"]):
            fresh.append(article)
    if not fresh:
        return {"articles": [], "executive_summary": "No qualifying new items found.", "watch_items": []}
    if not settings.openai_api_key:
        return _fallback(fresh, count)

    candidates = [{
        "i": i,
        "title": a["title"],
        "source": a["source"],
        "published_ist": a["published"].strftime("%d-%m-%Y %H:%M IST") if a["published"] else "unknown",
        "recency": a["recency"],
        "summary": a["summary"][:350],
        "url": a["url"],
    } for i, a in enumerate(fresh[:60])]

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM.format(
                        feedback=await feedback_memory(),
                        companies=", ".join(company_names or []),
                    ),
                },
                {"role": "user", "content": PROMPT.format(
                    count=count, category=category, candidates=json.dumps(candidates, ensure_ascii=False)
                )},
            ],
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=2500,
        )
        data = json.loads(response.choices[0].message.content)
        selected = []
        for choice in data.get("selected", []):
            idx = choice.get("index", -1)
            if isinstance(idx, int) and 0 <= idx < len(fresh):
                selected.append({**fresh[idx], **{k: v for k, v in choice.items() if k != "index"}})
        return {
            "articles": selected[:count],
            "executive_summary": data.get("executive_summary", ""),
            "watch_items": data.get("watch_items", [])[:3],
        }
    except Exception as e:  # noqa: BLE001
        log.error(f"AI analysis failed: {e}")
        return _fallback(fresh, count)


async def analyze_supplementary_articles(
    articles: list[dict],
    topics: list[dict],
    count: int = 8,
) -> dict:
    fresh = []
    for article in articles:
        if not await article_was_sent(article["url"]):
            fresh.append(article)
    if not fresh:
        return {
            "articles": [],
            "executive_summary": "No qualifying new supplementary items found.",
            "watch_items": [],
            "topics": topics,
        }
    if not settings.openai_api_key:
        result = _fallback(fresh, count)
        for article in result["articles"]:
            article["one_line_why"] = (
                f"Current development within the selected "
                f"{article.get('topic_name', 'supplementary')} topic."
            )
            article["investor_takeaway"] = (
                "Review potential effects on energy, trade, supply chains and markets."
            )
        result["topics"] = topics
        return result

    candidates = [{
        "i": index,
        "topic": article.get("topic_name", ""),
        "title": article["title"],
        "source": article["source"],
        "published_ist": (
            article["published"].strftime("%d-%m-%Y %H:%M IST")
            if article["published"]
            else "unknown"
        ),
        "recency": article["recency"],
        "summary": article["summary"][:350],
        "url": article["url"],
    } for index, article in enumerate(fresh[:80])]

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": SUPPLEMENTARY_SYSTEM.format(
                        feedback=await feedback_memory()
                    ),
                },
                {
                    "role": "user",
                    "content": SUPPLEMENTARY_PROMPT.format(
                        topics=", ".join(topic["name"] for topic in topics),
                        count=count,
                        candidates=json.dumps(candidates, ensure_ascii=False),
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=3000,
        )
        data = json.loads(response.choices[0].message.content)
        selected = []
        for choice in data.get("selected", []):
            index = choice.get("index", -1)
            if isinstance(index, int) and 0 <= index < len(fresh):
                selected.append({
                    **fresh[index],
                    **{key: value for key, value in choice.items() if key != "index"},
                })
        return {
            "articles": selected[:count],
            "executive_summary": data.get("executive_summary", ""),
            "watch_items": data.get("watch_items", [])[:3],
            "topics": topics,
        }
    except Exception as e:  # noqa: BLE001
        log.error(f"Supplementary AI analysis failed: {e}")
        result = _fallback(fresh, count)
        for article in result["articles"]:
            article["one_line_why"] = (
                f"Current development within the selected "
                f"{article.get('topic_name', 'supplementary')} topic."
            )
            article["investor_takeaway"] = (
                "Review potential effects on energy, trade, supply chains and markets."
            )
        result["topics"] = topics
        return result
