"""Feedback-aware AI analyst for relevance ranking and investor commentary."""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from solar.config import settings
from solar.database import article_was_sent, feedback_memory

log = logging.getLogger(__name__)
MIN_AI_IMPACT_SCORE = 60

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
Do not select an item unless its commercial impact score is at least 60. Only name an affected
company when the supplied candidate evidence explicitly supports it.
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
Do not select an item unless its business-impact score is at least 60.
Also provide a 3-sentence executive_summary and 3 watch_items.
Candidates:
{candidates}
Response: {{"selected": [...], "executive_summary": "...", "watch_items": ["...", "...", "..."]}}"""


def _fallback(articles: list[dict], count: int) -> dict:
    selected = []
    for article in articles[:count]:
        evidence = article.get("relevance_evidence") or []
        selected.append({
            **article,
            "impact_score": None,
            "impact": "not assessed",
            "one_line_why": "; ".join(evidence[:3]),
            "companies_affected": article.get("supported_companies", []),
            "investor_takeaway": (
                "AI impact analysis unavailable; review the linked qualified source."
            ),
            "analysis_status": "deterministic qualification only",
        })
    return {
        "articles": selected,
        "executive_summary": (
            "AI analysis was unavailable. Only stories that passed the deterministic "
            "India, solar and commercial-policy relevance gate are shown."
        ),
        "watch_items": [],
    }


def _validated_choice(choice: dict, article: dict) -> dict | None:
    impact_score = choice.get("impact_score")
    if not isinstance(impact_score, (int, float)):
        return None
    if not MIN_AI_IMPACT_SCORE <= impact_score <= 100:
        return None
    impact = choice.get("impact")
    if impact not in {"positive", "negative", "mixed", "neutral"}:
        return None
    if choice.get("url") and choice["url"] != article["url"]:
        return None
    supported = set(article.get("supported_companies", []))
    affected = [
        company
        for company in choice.get("companies_affected", [])
        if isinstance(company, str) and company in supported
    ]
    evidence = "; ".join(article.get("relevance_evidence", [])[:3])
    return {
        **article,
        "impact_score": round(float(impact_score), 1),
        "impact": impact,
        "one_line_why": evidence,
        "companies_affected": affected,
        "investor_takeaway": (
            f"AI impact assessment: {impact}. Verify implications in the linked source."
        ),
        "analysis_status": "AI-ranked qualified candidate",
    }


def _safe_summary(articles: list[dict]) -> str:
    if not articles:
        return "No qualifying high-relevance items were selected."
    titles = "; ".join(article["title"] for article in articles[:3])
    return (
        f"{len(articles)} qualified item(s) passed deterministic source and relevance "
        f"checks. Leading coverage: {titles}"
    )


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

    candidate_articles = fresh[:60]
    candidates = [{
        "i": i,
        "title": a["title"],
        "source": a["source"],
        "published_ist": a["published"].strftime("%d-%m-%Y %H:%M IST") if a["published"] else "unknown",
        "recency": a["recency"],
        "summary": a["summary"][:350],
        "url": a["url"],
        "deterministic_relevance_score": a["deterministic_relevance_score"],
        "relevance_evidence": a["relevance_evidence"],
        "supported_companies": a["supported_companies"],
    } for i, a in enumerate(candidate_articles)]

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
            if isinstance(idx, int) and 0 <= idx < len(candidate_articles):
                validated = _validated_choice(choice, candidate_articles[idx])
                if validated is not None:
                    selected.append(validated)
        return {
            "articles": selected[:count],
            "executive_summary": _safe_summary(selected[:count]),
            "watch_items": [],
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

    candidate_articles = fresh[:80]
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
    } for index, article in enumerate(candidate_articles)]

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
            if isinstance(index, int) and 0 <= index < len(candidate_articles):
                validated = _validated_choice(choice, candidate_articles[index])
                if validated is not None:
                    selected.append(validated)
        return {
            "articles": selected[:count],
            "executive_summary": _safe_summary(selected[:count]),
            "watch_items": [],
            "topics": topics,
        }
    except Exception as e:  # noqa: BLE001
        log.error(f"Supplementary AI analysis failed: {e}")
        result = _fallback(fresh, count)
        result["topics"] = topics
        return result
