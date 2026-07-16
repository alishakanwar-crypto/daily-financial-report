from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from solar.config import DEFAULT_COMPANIES, IST
from solar.data.prices import (
    OFFICIAL_MARKET_REGISTRY,
    _fetch_usd_inr,
    _parse_bse_graph,
    _parse_bse_history,
    _parse_nasdaq_rows,
    _price_row,
)
from solar.news.ai_analyst import _fallback, _validated_choice
from solar.news.fetcher import MIN_RELEVANCE_SCORE, qualify_article


class OfficialMarketDataTests(unittest.TestCase):
    @patch("solar.data.prices.httpx.get")
    def test_malformed_fbil_payload_degrades_to_unavailable_fx(self, get):
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"data": []}

        result = _fetch_usd_inr(date(2026, 7, 16))

        self.assertIsNone(result["rate"])
        self.assertEqual(result["source_name"], "FBIL USD/INR reference rate")
        self.assertIn("unexpected response shape", result["error"])

    def test_solar_finance_and_market_pipeline_contains_no_secondary_feed(self):
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "solar/data/financial_sources.py",
            root / "solar/data/ratios.py",
            root / "solar/data/prices.py",
            root / "solar/report/templates/report.html",
        ]
        text = "\n".join(path.read_text().lower() for path in paths)
        self.assertNotIn("yfinance", text)
        self.assertNotIn("query1.finance", text)
        self.assertNotIn("yahoo", text)

    def test_nasdaq_parser_and_completed_session_selection(self):
        payload = {
            "data": {
                "tradesTable": {
                    "rows": [
                        {
                            "date": "07/15/2026",
                            "close": "$6.28",
                            "volume": "1,940,870",
                            "open": "$6.24",
                            "high": "$6.33",
                            "low": "$6.17",
                        },
                        {
                            "date": "07/16/2026",
                            "close": "$6.40",
                            "volume": "100",
                            "open": "$6.30",
                            "high": "$6.45",
                            "low": "$6.25",
                        },
                    ]
                }
            }
        }
        rows = _parse_nasdaq_rows(payload)
        company = DEFAULT_COMPANIES[0]
        row = _price_row(
            company,
            OFFICIAL_MARKET_REGISTRY["RNW"],
            rows,
            rows,
            "https://api.nasdaq.com/official",
            date(2026, 7, 16),
        )
        self.assertEqual(row["trade_date"], "15-07-2026")
        self.assertEqual(row["close"], 6.28)
        self.assertEqual(row["volume"], 1_940_870)
        self.assertEqual(
            row["average_method"],
            "Derived typical price: (High + Low + Close) / 3",
        )
        self.assertIn("<svg", row["daily_chart_svg"])
        self.assertNotIn("yahoo", row["source_url"].lower())

    def test_bse_history_and_year_graph_parsers(self):
        html = """
        <table><tr class="TTRow">
          <td>15/07/26</td><td>2,829.55</td><td>2,843.00</td>
          <td>2,797.05</td><td>2,814.00</td><td>2,818.24</td>
          <td>18,054</td><td>1,000</td>
        </tr></table>
        """
        history = _parse_bse_history(html)
        graph = _parse_bse_graph({
            "Data": json.dumps([
                {
                    "dttm": "Wed Jul 16 2025 00:00:00",
                    "vale1": "3288.30",
                    "vole": "206347",
                },
                {
                    "dttm": "Wed Jul 15 2026 00:00:00",
                    "vale1": "2814.00",
                    "vole": "18054",
                },
            ])
        })
        self.assertEqual(history[0]["average"], 2818.24)
        self.assertEqual(history[0]["volume"], 18_054)
        self.assertEqual(graph[0]["close"], 3288.30)
        self.assertEqual(graph[-1]["date"], date(2026, 7, 15))

    def test_every_default_company_has_an_official_market_adapter(self):
        for company in DEFAULT_COMPANIES:
            with self.subTest(ticker=company.ticker):
                metadata = OFFICIAL_MARKET_REGISTRY[company.ticker]
                self.assertIn(metadata["adapter"], {"nasdaq", "bse"})
                self.assertNotIn(
                    "yahoo",
                    " ".join(metadata.values()).lower(),
                )


class NewsQualificationTests(unittest.TestCase):
    now = datetime(2026, 7, 16, 10, 0, tzinfo=IST)

    def article(self, title: str, summary: str, source: str = "Business Standard"):
        return {
            "title": title,
            "summary": summary,
            "source": source,
            "query": "India solar module manufacturing",
            "url": "https://example.com/story?utm_source=test",
            "published": self.now - timedelta(hours=3),
            "category": "industry",
        }

    def test_high_value_india_solar_story_qualifies(self):
        article = self.article(
            "Waaree announces new India solar module manufacturing capacity",
            "The listed manufacturer disclosed investment, factory capacity and orders.",
            "Waaree",
        )
        qualified = qualify_article(article, DEFAULT_COMPANIES, self.now)
        self.assertIsNotNone(qualified)
        self.assertGreaterEqual(
            qualified["deterministic_relevance_score"],
            MIN_RELEVANCE_SCORE,
        )
        self.assertIn("Waaree Energies", qualified["supported_companies"])
        self.assertNotIn("utm_source", qualified["url"])

    def test_generic_esg_and_overseas_only_stories_are_rejected(self):
        generic = self.article(
            "World Environment Day: tips for green living",
            "Generic ESG ranking and lifestyle advice for readers in India.",
        )
        overseas = {
            **self.article(
                "Australia opens a new solar farm",
                "The project expands renewable capacity and financing in Australia.",
            ),
            "query": "global solar",
        }
        self.assertIsNone(qualify_article(generic, DEFAULT_COMPANIES, self.now))
        self.assertIsNone(qualify_article(overseas, DEFAULT_COMPANIES, self.now))

    def test_weak_story_below_signal_threshold_is_rejected(self):
        weak = self.article(
            "India solar awareness event",
            "Students discussed clean power and sustainability.",
        )
        self.assertIsNone(qualify_article(weak, DEFAULT_COMPANIES, self.now))

    def test_ai_fallback_never_fabricates_score_50(self):
        qualified = qualify_article(
            self.article(
                "MNRE issues India solar manufacturing guideline",
                "The official policy updates ALMM requirements and module imports.",
                "MNRE",
            ),
            DEFAULT_COMPANIES,
            self.now,
        )
        result = _fallback([qualified], 1)
        self.assertIsNone(result["articles"][0]["impact_score"])
        self.assertEqual(
            result["articles"][0]["analysis_status"],
            "deterministic qualification only",
        )

    def test_ai_choice_requires_material_impact_and_supported_company(self):
        article = qualify_article(
            self.article(
                "Premier Energies wins India solar module order",
                "The company disclosed an order with manufacturing implications.",
                "Premier Energies",
            ),
            DEFAULT_COMPANIES,
            self.now,
        )
        low = _validated_choice({
            "impact_score": 50,
            "impact": "positive",
            "companies_affected": ["Premier Energies"],
        }, article)
        self.assertIsNone(low)
        valid = _validated_choice({
            "impact_score": 82,
            "impact": "positive",
            "companies_affected": ["Premier Energies", "Waaree Energies"],
            "one_line_why": "Order supports utilization.",
            "investor_takeaway": "Track execution.",
        }, article)
        self.assertEqual(valid["impact_score"], 82.0)
        self.assertEqual(valid["companies_affected"], ["Premier Energies"])


if __name__ == "__main__":
    unittest.main()
