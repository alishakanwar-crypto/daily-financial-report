from __future__ import annotations

import unittest

from solar.config import Company
from solar.data.financial_sources import cash_flow_source
from solar.data.ratios import _cash_flow_analysis
from solar.formulas import (
    FormulaInputError,
    FormulaValidationError,
    evaluate_formula,
    validate_formula,
)


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
                "capex": 48_817_700_000.0,
                "interest_expense": 2_805_000_000.0,
                "pretax_income": 50_517_900_000.0,
                "tax_provision": 11_676_400_000.0,
            },
        )
        self.assertEqual(values["capex"], 48_817_700_000.0)
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


if __name__ == "__main__":
    unittest.main()
