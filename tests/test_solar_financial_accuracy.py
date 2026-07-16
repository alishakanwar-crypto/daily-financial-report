from __future__ import annotations

import unittest
from unittest.mock import patch

from solar.config import DEFAULT_COMPANIES, Company
from solar.data.financial_sources import (
    cash_flow_source,
    classify_source_response,
    official_statement,
)
from solar.data.ratios import _company_ratios
from solar.formulas import (
    DEFAULT_FORMULAS,
    FormulaInputError,
    FormulaValidationError,
    evaluate_formula,
    validate_formula,
)
from solar.report.generator import render_report_html


class FormulaValidationTests(unittest.TestCase):
    def test_positive_and_negative_fcf_are_preserved(self):
        self.assertEqual(
            evaluate_formula(
                "operating_cf - capex",
                {"operating_cf": 100.0, "capex": 40.0},
            ),
            60.0,
        )
        self.assertEqual(
            evaluate_formula(
                "operating_cf - capex",
                {"operating_cf": 100.0, "capex": 140.0},
            ),
            -40.0,
        )

    def test_standard_fcff_formula_is_correct(self):
        expression = DEFAULT_FORMULAS["fcff"]["expression"]
        values = {
            "ebit": 100.0,
            "tax_rate": 0.25,
            "da": 20.0,
            "capex": 30.0,
            "change_nwc": 10.0,
        }
        self.assertEqual(evaluate_formula(expression, values), 55.0)
        values["capex"] = 100.0
        self.assertEqual(evaluate_formula(expression, values), -15.0)

    def test_missing_fcff_input_is_unavailable(self):
        with self.assertRaises(FormulaInputError):
            evaluate_formula(
                DEFAULT_FORMULAS["fcff"]["expression"],
                {
                    "ebit": None,
                    "tax_rate": 0.25,
                    "da": 20.0,
                    "capex": 30.0,
                    "change_nwc": 10.0,
                },
            )

    def test_unsafe_or_invalid_formulas_are_rejected(self):
        unsafe = [
            "operating_cf - invented_capex",
            "abs(operating_cf - capex)",
            "operating_cf.real - capex",
            "(operating_cf := capex)",
        ]
        for expression in unsafe:
            with self.subTest(expression=expression):
                with self.assertRaises(FormulaValidationError):
                    validate_formula(expression)
        with self.assertRaises(FormulaInputError):
            validate_formula("revenue / (revenue - revenue)")


class FilingOnlyRegistryTests(unittest.TestCase):
    expected_values = {
        "RNW": {"revenue": 132_196.0, "raw_unit": "INR million"},
        "WAAREEENER.NS": {"capex": 4_881.77, "raw_unit": "INR crore"},
        "PREMIERENE.NS": {"da": 4_524.99, "raw_unit": "INR million"},
        "VIKRAMSOLR.NS": {"net_income": 4_704.21, "raw_unit": "INR million"},
        "EMMVEE.NS": {"revenue": 504_987.73, "raw_unit": "INR lakh"},
    }

    def test_all_companies_use_only_official_filed_statements(self):
        for ticker, expected in self.expected_values.items():
            with self.subTest(ticker=ticker):
                statement = official_statement(ticker)
                self.assertIsNotNone(statement)
                self.assertEqual(
                    statement["raw_values"][next(
                        key for key in expected if key != "raw_unit"
                    )],
                    next(value for key, value in expected.items() if key != "raw_unit"),
                )
                self.assertEqual(statement["raw_unit"], expected["raw_unit"])
                self.assertNotIn("yahoo", statement["source_url"].lower())
                self.assertTrue(statement["source_type"].startswith("Official"))

    def test_field_provenance_is_complete_and_page_specific(self):
        for ticker in self.expected_values:
            with self.subTest(ticker=ticker):
                statement = official_statement(ticker)
                provenance = statement["field_provenance"]
                self.assertEqual(len(provenance), 19)
                for field, item in provenance.items():
                    self.assertEqual(item["field"], field)
                    self.assertIsNotNone(item["raw_value"])
                    self.assertIsNotNone(item["normalized_inr"])
                    self.assertTrue(item["statement_section"])
                    self.assertTrue(item["page_or_note"])
                    self.assertNotIn("yahoo", item["source_url"].lower())
                    self.assertEqual(item["scope"], "Consolidated")
                    self.assertIn(
                        item["validation_status"],
                        {"verified"},
                    )
        waaree = official_statement("WAAREEENER.NS")
        self.assertIn("#page=15", waaree["field_provenance"]["revenue"]["source_url"])
        self.assertEqual(
            waaree["field_provenance"]["total_assets_previous"][
                "statement_period"
            ],
            "As at 31-03-2025",
        )

    def test_corrected_waaree_and_emmvee_values_normalize_to_inr(self):
        waaree = official_statement("WAAREEENER.NS")
        self.assertEqual(waaree["values"]["current_assets"], 175_770_000_000.0)
        self.assertEqual(waaree["values"]["capex"], 48_817_700_000.0)
        self.assertEqual(
            waaree["field_provenance"]["capex"]["discrepancy_status"],
            "corrected",
        )
        emmvee = official_statement("EMMVEE.NS")
        self.assertEqual(emmvee["values"]["revenue"], 50_498_773_000.0)
        self.assertEqual(emmvee["values"]["capex"], 6_533_183_000.0)

    def test_cash_flow_compatibility_never_substitutes_market_values(self):
        values, metadata = cash_flow_source(
            "VIKRAMSOLR.NS",
            "31-03-2027",
            {
                "operating_cf": 999.0,
                "capex": 999.0,
                "interest_expense": 999.0,
            },
        )
        statement = official_statement("VIKRAMSOLR.NS")
        self.assertEqual(values["operating_cf"], statement["values"]["operating_cf"])
        self.assertEqual(values["capex"], statement["values"]["capex"])
        self.assertIsNone(values["interest_expense"])
        self.assertNotIn("yahoo", metadata["data_source_url"].lower())
        self.assertIn("no secondary", metadata["cross_check_detail"].lower())


class FilingOnlyRatioTests(unittest.TestCase):
    @patch("solar.data.ratios.validate_source_url")
    def test_average_balance_ratios_and_unavailable_fcff(self, validate_source):
        validate_source.return_value = {
            "status": "valid",
            "reason": "Validated official page",
            "checked_at": "10-07-2026 12:00:00 IST",
        }
        company = next(
            item for item in DEFAULT_COMPANIES
            if item.ticker == "WAAREEENER.NS"
        )
        row = _company_ratios(company)
        values = row["normalized_values"]
        expected_roe = round(
            values["net_income"]
            / ((values["total_equity"] + values["total_equity_previous"]) / 2)
            * 100,
            2,
        )
        expected_roa = round(
            values["net_income"]
            / ((values["total_assets"] + values["total_assets_previous"]) / 2)
            * 100,
            2,
        )
        self.assertEqual(row["roe"], expected_roe)
        self.assertEqual(row["roa"], expected_roa)
        self.assertIn("total_equity_previous", row["formula_audit"]["roe"]["formula"])
        self.assertIn("total_assets_previous", row["formula_audit"]["roa"]["formula"])
        self.assertIsNone(row["fcff"])
        self.assertIsNone(row["fcff_margin"])
        self.assertIsNone(row["interest_expense"])
        self.assertIn("Missing required input", row["formula_errors"]["fcff"])
        self.assertLess(row["free_cf"], 0)

    @patch("solar.data.ratios.validate_source_url")
    def test_every_formula_input_has_filing_provenance(self, validate_source):
        validate_source.return_value = {
            "status": "valid",
            "reason": "Validated official page",
            "checked_at": "10-07-2026 12:00:00 IST",
        }
        for company in DEFAULT_COMPANIES:
            with self.subTest(company=company.name):
                row = _company_ratios(company)
                for audit in row["formula_audit"].values():
                    self.assertEqual(
                        set(audit["formula_inputs"]),
                        set(audit["formula_input_provenance"]),
                    )
                    for provenance in audit["formula_input_provenance"].values():
                        self.assertNotIn(
                            "yahoo",
                            provenance["source_url"].lower(),
                        )

    @patch("solar.data.ratios.validate_source_url")
    def test_report_html_links_figures_and_contains_no_yahoo(self, validate_source):
        validate_source.return_value = {
            "status": "valid",
            "reason": "Validated official page",
            "checked_at": "10-07-2026 12:00:00 IST",
        }
        company = Company(
            "Premier Energies",
            "PREMIERENE.NS",
            "INR",
            "NSE",
            listed=True,
        )
        row = _company_ratios(company)
        html = render_report_html({
            "report_date": "Friday, 10 July 2026",
            "report_date_iso": "2026-07-10",
            "generated_at": "10-07-2026 12:00:00 IST",
            "companies": [company],
            "prices": {
                "trading_date": "Official completed-session prices unavailable",
                "rows": [],
                "usd_inr_rate": None,
                "usd_inr_date": None,
                "usd_inr_source_name": "FBIL USD/INR reference rate",
                "usd_inr_source_url": "https://www.fbil.org.in/",
            },
            "ratios": [row],
            "histories": {},
            "industry": {
                "executive_summary": "",
                "articles": [],
                "watch_items": [],
            },
            "government": {
                "executive_summary": "",
                "articles": [],
                "watch_items": [],
            },
            "supplementary": {
                "topics": [],
                "executive_summary": "",
                "articles": [],
                "watch_items": [],
            },
            "insights": {},
            "financial_formulas": [
                {
                    "label": formula["label"],
                    "expression": formula["expression"],
                }
                for formula in DEFAULT_FORMULAS.values()
            ],
            "feedback_url": "https://example.test/feedback",
        })
        self.assertNotIn("yahoo", html.lower())
        self.assertIn("Formula & Input Ledger", html)
        self.assertIn("Field-Level Filing Provenance", html)
        self.assertIn("#page=13", html)
        self.assertIn(DEFAULT_FORMULAS["fcff"]["expression"], html)


class SourceLinkValidationTests(unittest.TestCase):
    checked_at = "10-07-2026 12:00:00 IST"

    def test_valid_official_pdf_signature(self):
        result = classify_source_response(
            "https://www.waaree.com/results.pdf",
            200,
            "application/pdf",
            b"%PDF-1.7 data",
            self.checked_at,
        )
        self.assertEqual(result["status"], "valid")

    def test_non_approved_host_is_invalid(self):
        result = classify_source_response(
            "https://example.com/results.pdf",
            200,
            "application/pdf",
            b"%PDF-1.7 data",
            self.checked_at,
        )
        self.assertEqual(result["status"], "invalid")

    def test_pdf_url_returning_html_is_invalid(self):
        result = classify_source_response(
            "https://www.bseindia.com/results.pdf",
            200,
            "text/html",
            b"<html><title>Access denied</title></html>",
            self.checked_at,
        )
        self.assertEqual(result["status"], "invalid")
        self.assertIn("HTML", result["reason"])

    def test_official_403_is_classified_as_blocked(self):
        result = classify_source_response(
            "https://www.sec.gov/filing.htm",
            403,
            "text/html",
            b"",
            self.checked_at,
        )
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
