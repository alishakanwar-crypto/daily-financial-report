"""Filing-only comparative financial and cash-flow ratios."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

from solar.config import DEFAULT_COMPANIES, Company, IST, listed_companies
from solar.data.financial_sources import official_statement, validate_source_url
from solar.database import save_ratio_snapshot
from solar.formulas import (
    DEFAULT_FORMULAS,
    FormulaInputError,
    FormulaValidationError,
    evaluate_formula,
)

log = logging.getLogger(__name__)


def _n(value) -> Optional[float]:
    try:
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    except (TypeError, ValueError):
        return None


def _ratio(numerator, denominator, percent=False) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    value = numerator / denominator * (100 if percent else 1)
    return round(value, 2)


def _growth(current, previous) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def _average(current, previous) -> Optional[float]:
    if current is None or previous is None:
        return None
    return (current + previous) / 2


def _formula_expressions(formulas: Optional[dict[str, str]]) -> dict[str, str]:
    if formulas:
        return formulas
    return {
        key: formula["expression"]
        for key, formula in DEFAULT_FORMULAS.items()
    }


def _calculate_tax_rate(
    pretax_income: Optional[float],
    tax_provision: Optional[float],
) -> Optional[float]:
    if pretax_income in (None, 0) or tax_provision is None:
        return None
    rate = tax_provision / pretax_income
    return rate if 0 <= rate <= 1 else None


def _cash_flow_analysis(
    statement: dict,
    formulas: Optional[dict[str, str]] = None,
) -> dict:
    values = statement["values"]
    expressions = _formula_expressions(formulas)
    tax_rate = _calculate_tax_rate(
        values["pretax_income"],
        values["tax_provision"],
    )
    formula_values = {
        "operating_cf": values["operating_cf"],
        "capex": values["capex"],
        "interest_expense": None,
        "tax_rate": tax_rate,
        "ebit": values["ebit"],
        "da": values["da"],
        "change_nwc": values["change_nwc"],
        "revenue": values["revenue"],
    }

    formula_errors: dict[str, str] = {}
    results: dict[str, Optional[float]] = {}
    for key in ("free_cash_flow", "fcff"):
        try:
            results[key] = evaluate_formula(expressions[key], formula_values)
        except (FormulaInputError, FormulaValidationError, KeyError) as exc:
            results[key] = None
            formula_errors[key] = str(exc)

    free_cf = results["free_cash_flow"]
    if values["operating_cf"] is None or values["capex"] is None:
        fcf_explanation = "FCF is unavailable because a filed input is missing."
    elif free_cf is not None and free_cf < 0:
        fcf_explanation = (
            "FCF is negative because filed cash capital expenditure exceeds filed "
            "operating cash flow; the sign is preserved."
        )
    else:
        fcf_explanation = (
            "FCF equals filed operating cash flow less positive filed cash capex."
        )

    if results["fcff"] is None:
        fcff_explanation = (
            "FCFF is unavailable: compatible filed EBIT and change-in-operating-"
            "working-capital inputs are not disclosed for this snapshot. P&L finance "
            "costs are not substituted for cash interest."
        )
    else:
        fcff_explanation = "FCFF uses only compatible filed inputs."

    return {
        "raw_operating_cf": values["operating_cf"],
        "raw_capex": -values["capex"] if values["capex"] is not None else None,
        "raw_interest_expense": None,
        "raw_reported_free_cf": None,
        "operating_cf": values["operating_cf"],
        "capex": values["capex"],
        "interest_expense": None,
        "pretax_income": values["pretax_income"],
        "tax_provision": values["tax_provision"],
        "tax_rate": round(tax_rate, 6) if tax_rate is not None else None,
        "after_tax_interest": None,
        "free_cf": free_cf,
        "fcff": results["fcff"],
        "fcf_formula": expressions["free_cash_flow"],
        "fcff_formula": expressions["fcff"],
        "formula_errors": formula_errors,
        "cash_flow_explanation": f"{fcf_explanation} {fcff_explanation}",
        "cash_flow_statement_date": statement["statement_date"],
        "data_source_name": statement["source_name"],
        "data_source_url": statement["source_url"],
        "data_source_type": statement["source_type"],
        "source_captured_at": datetime.now(IST).strftime(
            "%d-%m-%Y %H:%M:%S IST"
        ),
        "source_freshness_status": "Latest configured complete filing period",
        "cross_check_status": "Filing-only validation",
        "cross_check_detail": (
            "No secondary finance source was queried, compared, or substituted."
        ),
        "source_input_note": (
            "Finance costs are shown in the provenance ledger but are excluded from "
            "FCFF because they are not equivalent to cash interest paid."
        ),
        "official_raw_capex": (
            -values["capex"] if values["capex"] is not None else None
        ),
    }


def _missing_provenance(
    field: str,
    statement: dict,
    reason: str = "Not disclosed on a compatible filed basis",
) -> dict:
    return {
        "field": field,
        "label": field.replace("_", " ").title(),
        "raw_value": None,
        "normalized_inr": None,
        "source_url": statement["source_url"],
        "statement_period": statement["statement_period"],
        "scope": statement["scope"],
        "audit_status": statement["audit_status"],
        "statement_section": "Unavailable",
        "page_or_note": reason,
        "validation_status": "unavailable",
        "caveat": reason,
    }


def _audit_entry(
    *,
    statement: dict,
    expression: str,
    inputs: dict[str, Optional[float]],
    result: Optional[float],
    units: str,
    provenance_fields: Optional[dict[str, str]] = None,
    unavailable_reason: str = "",
) -> dict:
    field_map = provenance_fields or {name: name for name in inputs}
    provenance: dict[str, dict] = {}
    source_urls: dict[str, str] = {}
    for input_name in inputs:
        field = field_map.get(input_name, input_name)
        item = statement["field_provenance"].get(field)
        if item is None:
            item = _missing_provenance(field, statement)
        provenance[input_name] = item
        source_urls[input_name] = item["source_url"]
    return {
        "formula": expression,
        "formula_inputs": inputs,
        "formula_source_urls": source_urls,
        "formula_input_provenance": provenance,
        "result": result,
        "units": units,
        "statement_date": statement["statement_date"],
        "statement_period": statement["statement_period"],
        "scope": statement["scope"],
        "unavailable_reason": unavailable_reason if result is None else "",
    }


def _company_ratios(
    company: Company,
    formulas: Optional[dict[str, str]] = None,
) -> dict:
    statement = official_statement(company.ticker)
    if statement is None:
        raise ValueError(
            f"No filed annual or quarterly statement configured for {company.ticker}"
        )

    values = statement["values"]
    revenue = values["revenue"]
    revenue_previous = values["revenue_previous"]
    net_income = values["net_income"]
    net_income_previous = values["net_income_previous"]
    total_assets = values["total_assets"]
    total_assets_previous = values["total_assets_previous"]
    current_assets = values["current_assets"]
    current_liabilities = values["current_liabilities"]
    inventory = values["inventory"]
    cash = values["cash"]
    total_debt = values["total_debt"]
    total_equity = values["total_equity"]
    total_equity_previous = values["total_equity_previous"]
    average_assets = _average(total_assets, total_assets_previous)
    average_equity = _average(total_equity, total_equity_previous)
    cash_flow = _cash_flow_analysis(statement, formulas)

    results = {
        "roe": _ratio(net_income, average_equity, True),
        "roa": _ratio(net_income, average_assets, True),
        "net_margin": _ratio(net_income, revenue, True),
        "debt_to_equity": _ratio(total_debt, total_equity),
        "debt_to_assets": _ratio(total_debt, total_assets),
        "current_ratio": _ratio(current_assets, current_liabilities),
        "quick_ratio": _ratio(
            current_assets - inventory
            if current_assets is not None and inventory is not None
            else None,
            current_liabilities,
        ),
        "operating_cf_margin": _ratio(cash_flow["operating_cf"], revenue, True),
        "fcf_margin": _ratio(cash_flow["free_cf"], revenue, True),
        "fcff_margin": _ratio(cash_flow["fcff"], revenue, True),
        "cash_conversion": _ratio(cash_flow["operating_cf"], net_income),
        "capex_to_revenue": _ratio(cash_flow["capex"], revenue, True),
        "revenue_growth": _growth(revenue, revenue_previous),
        "profit_growth": _growth(net_income, net_income_previous),
        "asset_turnover": _ratio(revenue, average_assets),
    }

    formula_audit = {
        "roe": _audit_entry(
            statement=statement,
            expression=(
                "net_income / ((total_equity + total_equity_previous) / 2) * 100"
            ),
            inputs={
                "net_income": net_income,
                "total_equity": total_equity,
                "total_equity_previous": total_equity_previous,
            },
            result=results["roe"],
            units="%",
        ),
        "roa": _audit_entry(
            statement=statement,
            expression=(
                "net_income / ((total_assets + total_assets_previous) / 2) * 100"
            ),
            inputs={
                "net_income": net_income,
                "total_assets": total_assets,
                "total_assets_previous": total_assets_previous,
            },
            result=results["roa"],
            units="%",
        ),
        "net_margin": _audit_entry(
            statement=statement,
            expression="net_income / revenue * 100",
            inputs={"net_income": net_income, "revenue": revenue},
            result=results["net_margin"],
            units="%",
        ),
        "debt_to_equity": _audit_entry(
            statement=statement,
            expression="total_debt / total_equity",
            inputs={"total_debt": total_debt, "total_equity": total_equity},
            result=results["debt_to_equity"],
            units="x",
        ),
        "debt_to_assets": _audit_entry(
            statement=statement,
            expression="total_debt / total_assets",
            inputs={"total_debt": total_debt, "total_assets": total_assets},
            result=results["debt_to_assets"],
            units="x",
        ),
        "current_ratio": _audit_entry(
            statement=statement,
            expression="current_assets / current_liabilities",
            inputs={
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
            },
            result=results["current_ratio"],
            units="x",
        ),
        "quick_ratio": _audit_entry(
            statement=statement,
            expression="(current_assets - inventory) / current_liabilities",
            inputs={
                "current_assets": current_assets,
                "inventory": inventory,
                "current_liabilities": current_liabilities,
            },
            result=results["quick_ratio"],
            units="x",
        ),
        "operating_cf_margin": _audit_entry(
            statement=statement,
            expression="operating_cf / revenue * 100",
            inputs={
                "operating_cf": cash_flow["operating_cf"],
                "revenue": revenue,
            },
            result=results["operating_cf_margin"],
            units="%",
        ),
        "fcf_margin": _audit_entry(
            statement=statement,
            expression="(operating_cf - capex) / revenue * 100",
            inputs={
                "operating_cf": cash_flow["operating_cf"],
                "capex": cash_flow["capex"],
                "revenue": revenue,
            },
            result=results["fcf_margin"],
            units="%",
        ),
        "fcff_margin": _audit_entry(
            statement=statement,
            expression=(
                "(ebit * (1 - tax_rate) + da - capex - change_nwc) "
                "/ revenue * 100"
            ),
            inputs={
                "ebit": values["ebit"],
                "tax_rate": cash_flow["tax_rate"],
                "da": values["da"],
                "capex": values["capex"],
                "change_nwc": values["change_nwc"],
                "revenue": revenue,
            },
            provenance_fields={
                "ebit": "ebit",
                "tax_rate": "tax_provision",
                "da": "da",
                "capex": "capex",
                "change_nwc": "change_nwc",
                "revenue": "revenue",
            },
            result=results["fcff_margin"],
            units="%",
            unavailable_reason=(
                "FCFF is unavailable because compatible filed inputs are missing."
            ),
        ),
        "cash_conversion": _audit_entry(
            statement=statement,
            expression="operating_cf / net_income",
            inputs={
                "operating_cf": cash_flow["operating_cf"],
                "net_income": net_income,
            },
            result=results["cash_conversion"],
            units="x",
        ),
        "capex_to_revenue": _audit_entry(
            statement=statement,
            expression="capex / revenue * 100",
            inputs={"capex": cash_flow["capex"], "revenue": revenue},
            result=results["capex_to_revenue"],
            units="%",
        ),
        "revenue_growth": _audit_entry(
            statement=statement,
            expression="(revenue - revenue_previous) / abs(revenue_previous) * 100",
            inputs={
                "revenue": revenue,
                "revenue_previous": revenue_previous,
            },
            result=results["revenue_growth"],
            units="%",
        ),
        "profit_growth": _audit_entry(
            statement=statement,
            expression=(
                "(net_income - net_income_previous) / "
                "abs(net_income_previous) * 100"
            ),
            inputs={
                "net_income": net_income,
                "net_income_previous": net_income_previous,
            },
            result=results["profit_growth"],
            units="%",
        ),
        "asset_turnover": _audit_entry(
            statement=statement,
            expression=(
                "revenue / ((total_assets + total_assets_previous) / 2)"
            ),
            inputs={
                "revenue": revenue,
                "total_assets": total_assets,
                "total_assets_previous": total_assets_previous,
            },
            result=results["asset_turnover"],
            units="x",
        ),
        "free_cf": _audit_entry(
            statement=statement,
            expression=cash_flow["fcf_formula"],
            inputs={
                "operating_cf": cash_flow["operating_cf"],
                "capex": cash_flow["capex"],
            },
            result=cash_flow["free_cf"],
            units="INR",
        ),
        "tax_rate": _audit_entry(
            statement=statement,
            expression="tax_provision / pretax_income * 100",
            inputs={
                "tax_provision": values["tax_provision"],
                "pretax_income": values["pretax_income"],
            },
            result=(
                cash_flow["tax_rate"] * 100
                if cash_flow["tax_rate"] is not None
                else None
            ),
            units="%",
        ),
        "fcff": _audit_entry(
            statement=statement,
            expression=cash_flow["fcff_formula"],
            inputs={
                "ebit": values["ebit"],
                "tax_rate": cash_flow["tax_rate"],
                "da": values["da"],
                "capex": values["capex"],
                "change_nwc": values["change_nwc"],
            },
            provenance_fields={
                "ebit": "ebit",
                "tax_rate": "tax_provision",
                "da": "da",
                "capex": "capex",
                "change_nwc": "change_nwc",
            },
            result=cash_flow["fcff"],
            units="INR",
            unavailable_reason=(
                "Compatible filed EBIT and change-in-working-capital inputs are "
                "unavailable; finance costs are not substituted."
            ),
        ),
    }

    source_validation = validate_source_url(statement["source_url"], timeout=8)
    document_validation = (
        validate_source_url(statement["document_url"], timeout=8)
        if statement["document_url"]
        and statement["document_url"] != statement["source_url"]
        else source_validation
    )
    source_urls = {
        field: provenance["source_url"]
        for field, provenance in statement["field_provenance"].items()
    }

    return {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": company.exchange,
        "currency": company.currency,
        "financial_currency": "INR",
        "statement_date": statement["statement_date"],
        "statement_period": statement["statement_period"],
        "captured_at": datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST"),
        "source_published_date": statement["published_date"],
        "data_source_name": statement["source_name"],
        "data_source_url": statement["source_url"],
        "data_source_type": statement["source_type"],
        "official_source_name": statement["source_name"],
        "official_source_url": statement["source_url"],
        "official_source_type": statement["source_type"],
        "document_url": statement["document_url"],
        "landing_url": statement["landing_url"],
        "source_link_status": source_validation["status"],
        "source_link_reason": source_validation["reason"],
        "source_link_checked_at": source_validation["checked_at"],
        "document_link_status": document_validation["status"],
        "document_link_reason": document_validation["reason"],
        "scope": statement["scope"],
        "audit_status": statement["audit_status"],
        "debt_definition": statement["debt_definition"],
        "raw_currency": statement["raw_currency"],
        "raw_unit": statement["raw_unit"],
        "raw_values": statement["raw_values"],
        "normalized_values": values,
        "statement_value_source_urls": source_urls,
        "field_provenance": statement["field_provenance"],
        "accuracy_ledger": list(statement["field_provenance"].values()),
        "latest_filing": statement["latest_filing"],
        "period_scope_validation": (
            f"Validated: {statement['statement_period']} / "
            f"{statement['scope']} / {statement['audit_status']}"
        ),
        "ratio_basis_note": (
            "ROE, ROA and asset turnover use average opening/closing balances. "
            "Debt ratios use borrowings excluding leases for all companies."
        ),
        "market_data_classification": "Market-derived metrics shown separately",
        "pe": None,
        "forward_pe": None,
        "price_to_book": None,
        "price_to_sales": None,
        "ev_to_ebitda": None,
        "dividend_yield": None,
        **results,
        "operating_margin": None,
        "ebitda_margin": None,
        "interest_coverage": None,
        **cash_flow,
        "formula_audit": formula_audit,
        "revenue": revenue,
        "revenue_previous": revenue_previous,
        "net_income": net_income,
        "net_income_previous": net_income_previous,
        "total_debt": total_debt,
        "cash": cash,
        "average_assets": average_assets,
        "average_equity": average_equity,
    }


async def fetch_and_store_ratios(
    companies: Optional[list[Company]] = None,
    formulas: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Calculate filing-only ratios and store one snapshot per statement date."""
    source = companies if companies is not None else DEFAULT_COMPANIES
    rows = []
    for company in listed_companies(source):
        try:
            row = _company_ratios(company, formulas)
            await save_ratio_snapshot(row)
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            log.error("official ratio calculation failed for %s: %s", company.ticker, exc)
            rows.append({
                "name": company.name,
                "ticker": company.ticker,
                "exchange": company.exchange,
                "currency": company.currency,
                "financial_currency": "INR",
                "statement_date": "N/A",
                "error": str(exc),
                "official_source_unavailable": True,
            })
    for company in source:
        if company.active and not company.listed:
            rows.append({
                "name": company.name,
                "ticker": None,
                "exchange": company.exchange,
                "currency": company.currency,
                "statement_date": "Not publicly reported",
                "unlisted": True,
                "note": company.note,
            })
    return rows
