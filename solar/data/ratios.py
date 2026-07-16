"""Comparative financial, fundamental, cash-flow, and operating ratios."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import httpx

from solar.config import DEFAULT_COMPANIES, Company, IST, listed_companies
from solar.data.financial_sources import (
    cash_flow_source,
    official_statement,
    validate_source_url,
)
from solar.database import save_ratio_snapshot
from solar.formulas import (
    DEFAULT_FORMULAS,
    FormulaInputError,
    FormulaValidationError,
    evaluate_formula,
)

log = logging.getLogger(__name__)


def _n(v) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _ratio(a, b, percent=False) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    value = a / b * (100 if percent else 1)
    return round(value, 2)


def _growth(cur, prev) -> Optional[float]:
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def _formula_expressions(formulas: Optional[dict[str, str]]) -> dict[str, str]:
    if formulas:
        return formulas
    return {
        key: formula["expression"]
        for key, formula in DEFAULT_FORMULAS.items()
    }


def _cash_flow_explanation(
    operating_cf: Optional[float],
    capex: Optional[float],
    free_cf: Optional[float],
    fcff: Optional[float],
    after_tax_interest: Optional[float],
) -> str:
    if operating_cf is None or capex is None:
        return "Cash-flow result is unavailable because operating cash flow or capex is missing."
    if free_cf is not None and free_cf < 0 and operating_cf >= 0 and capex > operating_cf:
        fcf_reason = (
            "FCF is negative because normalized capex exceeds operating cash flow."
        )
    elif free_cf is not None:
        fcf_reason = "FCF follows the saved formula using normalized positive capex."
    else:
        fcf_reason = "FCF could not be calculated with the saved formula."
    if fcff is None:
        return f"{fcf_reason} FCFF is unavailable because a required input is missing."
    if fcff < 0 and after_tax_interest is not None:
        return (
            f"{fcf_reason} FCFF remains negative because capex exceeds operating "
            "cash flow plus after-tax financing expense."
        )
    if fcff >= 0:
        return (
            f"{fcf_reason} FCFF is positive after adding back the after-tax "
            "financing expense."
        )
    return fcf_reason


def _cash_flow_analysis(
    company: Company,
    market_statement_date: str,
    operating_cf: Optional[float],
    raw_capex: Optional[float],
    raw_interest: Optional[float],
    pretax_income: Optional[float],
    tax_provision: Optional[float],
    ebit: Optional[float],
    da: Optional[float],
    change_nwc: Optional[float],
    revenue: Optional[float],
    formulas: Optional[dict[str, str]],
    raw_reported_free_cf: Optional[float] = None,
) -> dict:
    expressions = _formula_expressions(formulas)
    normalized_market_inputs = {
        "operating_cf": operating_cf,
        "capex": abs(raw_capex) if raw_capex is not None else None,
        "interest_expense": abs(raw_interest) if raw_interest is not None else None,
        "pretax_income": pretax_income,
        "tax_provision": tax_provision,
    }
    sourced_inputs, source_metadata = cash_flow_source(
        company.ticker,
        market_statement_date,
        normalized_market_inputs,
    )
    sourced_pretax = sourced_inputs.get("pretax_income")
    sourced_tax = sourced_inputs.get("tax_provision")
    tax_rate = None
    if sourced_pretax not in (None, 0) and sourced_tax is not None:
        calculated_tax_rate = sourced_tax / sourced_pretax
        if 0 <= calculated_tax_rate <= 1:
            tax_rate = calculated_tax_rate
    values = {
        "operating_cf": sourced_inputs.get("operating_cf"),
        "capex": sourced_inputs.get("capex"),
        "interest_expense": sourced_inputs.get("interest_expense"),
        "tax_rate": tax_rate,
        "ebit": ebit,
        "da": da,
        "change_nwc": change_nwc,
        "revenue": revenue,
    }

    formula_errors = {}
    results = {}
    for key in ("free_cash_flow", "fcff"):
        try:
            results[key] = evaluate_formula(expressions[key], values)
        except (FormulaInputError, FormulaValidationError, KeyError) as exc:
            results[key] = None
            formula_errors[key] = str(exc)

    interest_expense = values["interest_expense"]
    after_tax_interest = None
    if interest_expense is not None and tax_rate is not None:
        after_tax_interest = interest_expense * (1 - tax_rate)
    free_cf = results["free_cash_flow"]
    fcff = results["fcff"]
    return {
        "raw_operating_cf": operating_cf,
        "raw_capex": raw_capex,
        "raw_interest_expense": raw_interest,
        "raw_reported_free_cf": raw_reported_free_cf,
        "operating_cf": values["operating_cf"],
        "capex": values["capex"],
        "interest_expense": interest_expense,
        "pretax_income": sourced_pretax,
        "tax_provision": sourced_tax,
        "tax_rate": round(tax_rate, 6) if tax_rate is not None else None,
        "after_tax_interest": after_tax_interest,
        "free_cf": free_cf,
        "fcff": fcff,
        "fcf_formula": expressions["free_cash_flow"],
        "fcff_formula": expressions["fcff"],
        "formula_errors": formula_errors,
        "cash_flow_explanation": _cash_flow_explanation(
            values["operating_cf"],
            values["capex"],
            free_cf,
            fcff,
            after_tax_interest,
        ),
        **source_metadata,
    }


def _company_ratios(
    company: Company,
    formulas: Optional[dict[str, str]] = None,
) -> dict:
    statement = official_statement(company.ticker)
    if statement is None:
        raise ValueError(f"No official financial statement configured for {company.ticker}")
    values = statement["values"]
    revenue = values["revenue"]
    revenue_prev = values["revenue_previous"]
    net_income = values["net_income"]
    net_income_prev = values["net_income_previous"]
    pretax_income = values["pretax_income"]
    tax_provision = values["tax_provision"]
    interest = values["finance_costs"]
    da = values["da"]
    assets = values["total_assets"]
    current_assets = values["current_assets"]
    current_liabilities = values["current_liabilities"]
    inventory = values["inventory"]
    cash = values["cash"]
    debt = values["total_debt"]
    equity = values["total_equity"]
    operating_cf = values["operating_cf"]
    raw_capex = values["capex"]
    statement_date = statement["statement_date"]
    cash_flow = _cash_flow_analysis(
        company,
        statement_date,
        operating_cf,
        raw_capex,
        interest,
        pretax_income,
        tax_provision,
        pretax_income + interest
        if pretax_income is not None and interest is not None
        else None,
        da,
        None,
        revenue,
        formulas,
    )
    source_urls = {
        field: statement["source_url"]
        for field, value in values.items()
        if value is not None
    }
    metric_inputs = {
        "roe": ("(net_income / total_equity) * 100", {
            "net_income": net_income,
            "total_equity": equity,
        }),
        "roa": ("(net_income / total_assets) * 100", {
            "net_income": net_income,
            "total_assets": assets,
        }),
        "net_margin": ("(net_income / revenue) * 100", {
            "net_income": net_income,
            "revenue": revenue,
        }),
        "debt_to_equity": ("total_debt / total_equity", {
            "total_debt": debt,
            "total_equity": equity,
        }),
        "debt_to_assets": ("total_debt / total_assets", {
            "total_debt": debt,
            "total_assets": assets,
        }),
        "current_ratio": ("current_assets / current_liabilities", {
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
        }),
        "quick_ratio": (
            "(current_assets - inventory) / current_liabilities",
            {
                "current_assets": current_assets,
                "inventory": inventory,
                "current_liabilities": current_liabilities,
            },
        ),
        "operating_cf_margin": ("(operating_cf / revenue) * 100", {
            "operating_cf": cash_flow["operating_cf"],
            "revenue": revenue,
        }),
        "fcf_margin": ("(free_cf / revenue) * 100", {
            "free_cf": cash_flow["free_cf"],
            "revenue": revenue,
        }),
        "fcff_margin": ("(fcff / revenue) * 100", {
            "fcff": cash_flow["fcff"],
            "revenue": revenue,
        }),
        "cash_conversion": ("operating_cf / net_income", {
            "operating_cf": cash_flow["operating_cf"],
            "net_income": net_income,
        }),
        "capex_to_revenue": ("(capex / revenue) * 100", {
            "capex": cash_flow["capex"],
            "revenue": revenue,
        }),
        "revenue_growth": (
            "((revenue - revenue_previous) / abs(revenue_previous)) * 100",
            {"revenue": revenue, "revenue_previous": revenue_prev},
        ),
        "profit_growth": (
            "((net_income - net_income_previous) / abs(net_income_previous)) * 100",
            {"net_income": net_income, "net_income_previous": net_income_prev},
        ),
        "asset_turnover": ("revenue / total_assets", {
            "revenue": revenue,
            "total_assets": assets,
        }),
    }
    results = {
        "roe": _ratio(net_income, equity, True),
        "roa": _ratio(net_income, assets, True),
        "net_margin": _ratio(net_income, revenue, True),
        "debt_to_equity": _ratio(debt, equity),
        "debt_to_assets": _ratio(debt, assets),
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
        "revenue_growth": _growth(revenue, revenue_prev),
        "profit_growth": _growth(net_income, net_income_prev),
        "asset_turnover": _ratio(revenue, assets),
    }
    formula_audit = {}
    for key, (expression, inputs) in metric_inputs.items():
        formula_audit[key] = {
            "formula": expression,
            "formula_inputs": inputs,
            "formula_source_urls": {
                input_name: statement["source_url"] for input_name in inputs
            },
            "result": results[key],
            "units": "%" if key in {
                "roe",
                "roa",
                "net_margin",
                "operating_cf_margin",
                "fcf_margin",
                "fcff_margin",
                "capex_to_revenue",
                "revenue_growth",
                "profit_growth",
            } else "x",
        }
    formula_audit["free_cf"] = {
        "formula": cash_flow["fcf_formula"],
        "formula_inputs": {
            "operating_cf": cash_flow["operating_cf"],
            "capex": cash_flow["capex"],
        },
        "formula_source_urls": {
            "operating_cf": statement["source_url"],
            "capex": statement["source_url"],
        },
        "result": cash_flow["free_cf"],
        "units": "INR",
    }
    formula_audit["tax_rate"] = {
        "formula": "tax_provision / pretax_income",
        "formula_inputs": {
            "tax_provision": tax_provision,
            "pretax_income": pretax_income,
        },
        "formula_source_urls": {
            "tax_provision": statement["source_url"],
            "pretax_income": statement["source_url"],
        },
        "result": cash_flow["tax_rate"] * 100
        if cash_flow["tax_rate"] is not None
        else None,
        "units": "%",
    }
    formula_audit["fcff"] = {
        "formula": cash_flow["fcff_formula"],
        "formula_inputs": {
            "operating_cf": cash_flow["operating_cf"],
            "interest_expense": cash_flow["interest_expense"],
            "tax_rate": cash_flow["tax_rate"],
            "capex": cash_flow["capex"],
        },
        "formula_source_urls": {
            input_name: statement["source_url"]
            for input_name in ("operating_cf", "interest_expense", "tax_rate", "capex")
        },
        "result": cash_flow["fcff"],
        "units": "INR",
    }
    source_validation = validate_source_url(statement["source_url"], timeout=8)
    document_validation = (
        validate_source_url(statement["document_url"], timeout=8)
        if statement["document_url"]
        and statement["document_url"] != statement["source_url"]
        else source_validation
    )

    return {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": company.exchange,
        "currency": company.currency,
        "financial_currency": "INR",
        "statement_date": statement_date,
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
        "raw_currency": statement["raw_currency"],
        "raw_unit": statement["raw_unit"],
        "raw_values": statement["raw_values"],
        "normalized_values": values,
        "statement_value_source_urls": source_urls,
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
        "revenue_previous": revenue_prev,
        "net_income": net_income,
        "net_income_previous": net_income_prev,
        "total_debt": debt,
        "cash": cash,
    }


_FUNDAMENTAL_TYPES = (
    "trailingMarketCap,trailingPeRatio,trailingForwardPeRatio,trailingPsRatio,"
    "trailingEnterpriseValue,trailingDividendYield,annualTotalRevenue,"
    "annualNetIncome,annualEBIT,annualEBITDA,annualInterestExpense,"
    "annualPretaxIncome,annualTaxProvision,"
    "annualDepreciationAndAmortizationInIncomeStatement,"
    "annualChangeInWorkingCapital,"
    "annualTotalAssets,annualCurrentAssets,annualCurrentLiabilities,"
    "annualInventory,annualCashCashEquivalentsAndShortTermInvestments,"
    "annualTotalDebt,annualStockholdersEquity,annualOperatingCashFlow,"
    "annualCapitalExpenditure,annualFreeCashFlow"
)


def _timeseries(data: dict) -> dict[str, list[dict]]:
    values = {}
    for result in data.get("timeseries", {}).get("result", []):
        types = result.get("meta", {}).get("type", [])
        if not types:
            continue
        metric = types[0]
        values[metric] = sorted(result.get(metric, []), key=lambda item: item.get("asOfDate", ""))
    return values


def _latest(series: dict[str, list[dict]], metric: str, offset: int = 0) -> Optional[float]:
    values = series.get(metric, [])
    if len(values) <= offset:
        return None
    return _n(values[-1 - offset].get("reportedValue", {}).get("raw"))


def _latest_currency(series: dict[str, list[dict]], metric: str) -> Optional[str]:
    values = series.get(metric, [])
    if not values:
        return None
    latest = values[-1]
    return (
        latest.get("currencyCode")
        or latest.get("reportedValue", {}).get("currencyCode")
    )


def _company_ratios_fallback(
    company: Company,
    formulas: Optional[dict[str, str]] = None,
) -> dict:
    now_ist = datetime.now(IST)
    response = httpx.get(
        f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{company.ticker}",
        params={
            "symbol": company.ticker,
            "type": _FUNDAMENTAL_TYPES,
            "period1": int((now_ist - timedelta(days=1460)).timestamp()),
            "period2": int((now_ist + timedelta(days=1)).timestamp()),
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    series = _timeseries(response.json())
    statement_dates = [
        item.get("asOfDate")
        for metric, values in series.items()
        if metric.startswith("annual")
        for item in values
        if item.get("asOfDate")
    ]
    if not statement_dates:
        raise ValueError("Yahoo fundamentals returned no annual statements")

    revenue = _latest(series, "annualTotalRevenue")
    revenue_prev = _latest(series, "annualTotalRevenue", 1)
    net_income = _latest(series, "annualNetIncome")
    net_income_prev = _latest(series, "annualNetIncome", 1)
    ebit = _latest(series, "annualEBIT")
    ebitda = _latest(series, "annualEBITDA")
    interest = _latest(series, "annualInterestExpense")
    pretax_income = _latest(series, "annualPretaxIncome")
    tax_provision = _latest(series, "annualTaxProvision")
    da = _latest(series, "annualDepreciationAndAmortizationInIncomeStatement")
    change_nwc = _latest(series, "annualChangeInWorkingCapital")
    assets = _latest(series, "annualTotalAssets")
    current_assets = _latest(series, "annualCurrentAssets")
    current_liabilities = _latest(series, "annualCurrentLiabilities")
    inventory = _latest(series, "annualInventory") or 0
    cash = _latest(series, "annualCashCashEquivalentsAndShortTermInvestments")
    debt = _latest(series, "annualTotalDebt")
    equity = _latest(series, "annualStockholdersEquity")
    operating_cf = _latest(series, "annualOperatingCashFlow")
    raw_capex = _latest(series, "annualCapitalExpenditure")
    raw_reported_free_cf = _latest(series, "annualFreeCashFlow")
    market_cap = _latest(series, "trailingMarketCap")
    enterprise_value = _latest(series, "trailingEnterpriseValue")
    dividend_yield = _latest(series, "trailingDividendYield")
    financial_currency = (
        _latest_currency(series, "annualTotalRevenue")
        or _latest_currency(series, "annualTotalAssets")
        or company.currency
    )
    statement_date = datetime.fromisoformat(max(statement_dates)).strftime("%d-%m-%Y")
    cash_flow = _cash_flow_analysis(
        company,
        statement_date,
        operating_cf,
        raw_capex,
        interest,
        pretax_income,
        tax_provision,
        ebit,
        da,
        change_nwc,
        revenue,
        formulas,
        raw_reported_free_cf,
    )

    return {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": company.exchange,
        "currency": company.currency,
        "financial_currency": financial_currency,
        "statement_date": statement_date,
        "captured_at": now_ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "pe": _latest(series, "trailingPeRatio"),
        "forward_pe": _latest(series, "trailingForwardPeRatio"),
        "price_to_book": _ratio(market_cap, equity),
        "price_to_sales": _latest(series, "trailingPsRatio") or _ratio(market_cap, revenue),
        "ev_to_ebitda": _ratio(enterprise_value, ebitda),
        "dividend_yield": round(dividend_yield * 100, 2) if dividend_yield else None,
        "roe": _ratio(net_income, equity, True),
        "roa": _ratio(net_income, assets, True),
        "net_margin": _ratio(net_income, revenue, True),
        "operating_margin": _ratio(ebit, revenue, True),
        "ebitda_margin": _ratio(ebitda, revenue, True),
        "debt_to_equity": _ratio(debt, equity),
        "debt_to_assets": _ratio(debt, assets),
        "current_ratio": _ratio(current_assets, current_liabilities),
        "quick_ratio": _ratio(
            (current_assets - inventory) if current_assets is not None else None,
            current_liabilities,
        ),
        "interest_coverage": _ratio(ebit, abs(interest) if interest else None),
        **cash_flow,
        "operating_cf_margin": _ratio(cash_flow["operating_cf"], revenue, True),
        "fcf_margin": _ratio(cash_flow["free_cf"], revenue, True),
        "fcff_margin": _ratio(cash_flow["fcff"], revenue, True),
        "cash_conversion": _ratio(cash_flow["operating_cf"], net_income),
        "capex_to_revenue": _ratio(cash_flow["capex"], revenue, True),
        "revenue_growth": _growth(revenue, revenue_prev),
        "profit_growth": _growth(net_income, net_income_prev),
        "asset_turnover": _ratio(revenue, assets),
        "revenue": revenue,
        "net_income": net_income,
        "total_debt": debt,
        "cash": cash,
        "source": "Yahoo Finance fundamentals timeseries fallback",
    }


async def fetch_and_store_ratios(
    companies: Optional[list[Company]] = None,
    formulas: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Fetch current ratios and upsert one snapshot per statement date."""
    source = companies if companies is not None else DEFAULT_COMPANIES
    rows = []
    for company in listed_companies(source):
        try:
            row = _company_ratios(company, formulas)
            await save_ratio_snapshot(row)
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            log.error(f"official ratio calculation failed for {company.ticker}: {e}")
            rows.append({
                "name": company.name,
                "ticker": company.ticker,
                "exchange": company.exchange,
                "currency": company.currency,
                "financial_currency": "INR",
                "statement_date": "N/A",
                "error": str(e),
                "official_source_unavailable": True,
            })
    # Include unlisted company explicitly to avoid implying missing coverage.
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
