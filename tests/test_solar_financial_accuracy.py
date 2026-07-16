from __future__ import annotations

import unittest
from unittest.mock import patch

from solar.config import Company
from solar.data.financial_sources import (
    cash_flow_source,
    classify_source_response,
    official_statement,
)
from solar.data.ratios import _cash_flow_analysis, _company_ratios
from solar.formulas import (
    FormulaInputError,
    FormulaValidationError,
    evaluate_formula,
    validate_formula,
)
from solar.report.generator import render_report_html


class FormulaValidationTests(unittest.TestCase):
    def test_positive_free_cash_flow(self):
        result = evaluate_formula(
            "operating_cf - capex",
            {"operating_cf": 100.0, "capex": 40.0},
        )
        self.assertEqual(result, 60.0)

    def test_positive_fcff_after_after_tax_interest_addback(self):
        result = evaluate_formula(
            "operating_cf + interest_expense * (1 - tax_rate) - capex",
            {
                "operating_cf": 100.0,
                "interest_expense": 20.0,
                "tax_rate": 0.25,
                "capex": 110.0,
            },
        )
        self.assertEqual(result, 5.0)

    def test_legitimately_negative_fcff(self):
        result = evaluate_formula(
            "operating_cf + interest_expense * (1 - tax_rate) - capex",
            {
                "operating_cf": 100.0,
                "interest_expense": 20.0,
                "tax_rate": 0.25,
                "capex": 140.0,
            },
        )
        self.assertEqual(result, -25.0)

    def test_missing_tax_or_interest_is_reported(self):
        with self.assertRaises(FormulaInputError):
            evaluate_formula(
                "operating_cf + interest_expense * (1 - tax_rate) - capex",
                {
                    "operating_cf": 100.0,
                    "interest_expense": None,
                    "tax_rate": None,
                    "capex": 40.0,
                },
            )

    def test_unknown_variable_is_rejected(self):
        with self.assertRaises(FormulaValidationError):
            validate_formula("operating_cf - invented_capex")

    def test_function_call_is_rejected(self):
        with self.assertRaises(FormulaValidationError):
            validate_formula("abs(operating_cf - capex)")

    def test_attribute_access_is_rejected(self):
        with self.assertRaises(FormulaValidationError):
            validate_formula("operating_cf.real - capex")

    def test_assignment_is_rejected(self):
        with self.assertRaises(FormulaValidationError):
            validate_formula("(operating_cf := capex)")

    def test_division_by_zero_is_rejected(self):
        with self.assertRaises(FormulaInputError):
            validate_formula("revenue / (revenue - revenue)")


class CashFlowNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.company = Company(
            "Test Solar",
            "TESTSOLAR.NS",
            "INR",
            "NSE",
            listed=True,
        )

    def test_negative_yahoo_capex_is_normalized_to_positive_outflow(self):
        result = _cash_flow_analysis(
            company=self.company,
            market_statement_date="31-03-2026",
            operating_cf=100.0,
            raw_capex=-140.0,
            raw_interest=20.0,
            pretax_income=80.0,
            tax_provision=20.0,
            ebit=90.0,
            da=10.0,
            change_nwc=5.0,
            revenue=300.0,
            formulas=None,
        )
        self.assertEqual(result["capex"], 140.0)
        self.assertEqual(result["free_cf"], -40.0)
        self.assertEqual(result["fcff"], -25.0)
        self.assertIn("capex exceeds operating cash flow", result["cash_flow_explanation"])

    def test_positive_fcff_is_not_forced_to_match_fcf(self):
        result = _cash_flow_analysis(
            company=self.company,
            market_statement_date="31-03-2026",
            operating_cf=100.0,
            raw_capex=-110.0,
            raw_interest=20.0,
            pretax_income=80.0,
            tax_provision=20.0,
            ebit=90.0,
            da=10.0,
            change_nwc=5.0,
            revenue=300.0,
            formulas=None,
        )
        self.assertEqual(result["free_cf"], -10.0)
        self.assertEqual(result["fcff"], 5.0)


class SourceCrossCheckTests(unittest.TestCase):
    def test_renew_stale_market_period_is_replaced_by_official_fy26(self):
        values, metadata = cash_flow_source(
            "RNW",
            "31-03-2025",
            {
                "operating_cf": 67_565_000_000.0,
                "capex": 93_659_000_000.0,
                "interest_expense": 50_374_000_000.0,
                "pretax_income": 10_034_000_000.0,
                "tax_provision": 5_443_000_000.0,
            },
        )
        self.assertEqual(values["operating_cf"], 82_824_000_000.0)
        self.assertEqual(metadata["cash_flow_statement_date"], "31-03-2026")
        self.assertIn("replace stale", metadata["source_freshness_status"])

    def test_current_official_source_is_marked_verified(self):
        values, metadata = cash_flow_source(
            "WAAREEENER.NS",
            "31-03-2026",
            {
                "operating_cf": 16_269_500_000.0,
                "capex": 43_817_700_000.0,
                "interest_expense": 2_805_000_000.0,
                "pretax_income": 50_517_900_000.0,
                "tax_provision": 11_676_400_000.0,
            },
        )
        self.assertEqual(values["capex"], 43_817_700_000.0)
        self.assertEqual(
            metadata["cross_check_status"],
            "Verified against official filing",
        )

    def test_official_line_item_discrepancy_is_disclosed(self):
        values, metadata = cash_flow_source(
            "VIKRAMSOLR.NS",
            "31-03-2026",
            {
                "operating_cf": 6_295_480_000.0,
                "capex": 7_220_930_000.0,
                "interest_expense": 1_217_090_000.0,
                "pretax_income": 6_469_610_000.0,
                "tax_provision": 1_765_400_000.0,
            },
        )
        self.assertEqual(values["interest_expense"], 1_605_600_000.0)
        self.assertIn(
            "interest/finance cost Yahoo",
            metadata["cross_check_detail"],
        )

    def test_newer_market_period_never_replaces_official_statement(self):
        values, metadata = cash_flow_source(
            "PREMIERENE.NS",
            "31-03-2027",
            {
                "operating_cf": 999.0,
                "capex": 999.0,
                "interest_expense": 999.0,
                "pretax_income": 999.0,
                "tax_provision": 999.0,
            },
        )
        self.assertEqual(values["operating_cf"], 12_610_560_000.0)
        self.assertEqual(metadata["data_source_type"], "Official company filing")


class OfficialStatementRegistryTests(unittest.TestCase):
    def test_emmvee_lakh_values_are_normalized_to_rupees(self):
        statement = official_statement("EMMVEE.NS")
        self.assertIsNotNone(statement)
        self.assertEqual(statement["currency"], "INR")
        self.assertEqual(statement["raw_unit"], "INR lakh")
        self.assertEqual(statement["values"]["revenue"], 50_491_773_000.0)
        self.assertNotIn("finance.yahoo.com", statement["source_url"])

    def test_waaree_uses_correct_audited_capex(self):
        statement = official_statement("WAAREEENER.NS")
        self.assertEqual(statement["raw_values"]["capex"], 4_381.77)
        self.assertEqual(statement["values"]["capex"], 43_817_700_000.0)

    def test_unverified_waaree_current_assets_remain_missing(self):
        statement = official_statement("WAAREEENER.NS")
        self.assertIsNone(statement["values"]["current_assets"])

    @patch("solar.data.ratios.validate_source_url")
    def test_ratio_row_uses_official_inr_inputs_and_formula_metadata(
        self,
        validate_source,
    ):
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
        self.assertEqual(row["financial_currency"], "INR")
        self.assertEqual(row["revenue"], 78_243_740_000.0)
        self.assertEqual(
            row["formula_audit"]["roe"]["formula"],
            "(net_income / total_equity) * 100",
        )
        self.assertEqual(
            row["formula_audit"]["roe"]["formula_source_urls"]["net_income"],
            row["official_source_url"],
        )
        self.assertIsNone(row["pe"])

        html = render_report_html({
            "report_date": "Friday, 10 July 2026",
            "report_date_iso": "2026-07-10",
            "generated_at": "10-07-2026 12:00:00 IST",
            "companies": [company],
            "prices": {
                "trading_date": "09-07-2026",
                "rows": [],
                "usd_inr_rate": None,
                "usd_inr_source_url": "",
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
            "financial_formulas": [],
            "feedback_url": "https://example.test/feedback",
        })
        self.assertIn(
            f'href="{row["official_source_url"]}">₹78.24 bn</a>',
            html,
        )
        self.assertIn("(net_income / total_equity) * 100", html)
        self.assertIn("Formula & Input Ledger", html)


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

    def test_html_block_body_overrides_misleading_pdf_content_type(self):
        result = classify_source_response(
            "https://www.bseindia.com/results.pdf",
            200,
            "application/pdf",
            b"<html><title>Request Rejected</title></html>",
            self.checked_at,
        )
        self.assertEqual(result["status"], "invalid")

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
