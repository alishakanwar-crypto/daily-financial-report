"""Comparative financial, fundamental, cash-flow, and operating ratios."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import httpx
import yfinance as yf

from solar.config import DEFAULT_COMPANIES, Company, IST, listed_companies
from solar.data.financial_sources import cash_flow_source
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


def _line(df, *names: str, col=0) -> Optional[float]:
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index and len(df.columns) > col:
            return _n(df.loc[name].iloc[col])
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


def _statement_date(tk: yf.Ticker) -> str:
    frames = [tk.income_stmt, tk.balance_sheet, tk.cashflow]
    dates = []
    for df in frames:
        if df is not None and not df.empty:
            for c in df.columns:
                try:
                    dates.append(c.date())
                except AttributeError:
                    pass
    return max(dates).strftime("%d-%m-%Y") if dates else "N/A"


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
            "FCF is negative because normalized capex exceeds operating cash flow "
            f"by {capex - operating_cf:,.0f}."
        )
    elif free_cf is not None:
        fcf_reason = "FCF follows the saved formula using normalized positive capex."
    else:
        fcf_reason = "FCF could not be calculated with the saved formula."
    if fcff is None:
        return f"{fcf_reason} FCFF is unavailable because a required input is missing."
    if fcff < 0 and after_tax_interest is not None:
        gap = capex - operating_cf - after_tax_interest
        return (
            f"{fcf_reason} FCFF remains negative because capex exceeds operating "
            f"cash flow plus after-tax financing expense by {gap:,.0f}."
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
    tk = yf.Ticker(company.ticker)
    info = tk.info or {}
    inc, bs, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow

    revenue = _line(inc, "Total Revenue")
    revenue_prev = _line(inc, "Total Revenue", col=1)
    net_income = _line(inc, "Net Income")
    net_income_prev = _line(inc, "Net Income", col=1)
    ebit = _line(inc, "EBIT", "Operating Income")
    ebitda = _line(inc, "EBITDA", "Normalized EBITDA")
    interest = _line(inc, "Interest Expense", "Interest Expense Non Operating")
    pretax_income = _line(inc, "Pretax Income", "Income Before Tax")
    tax_provision = _line(inc, "Tax Provision", "Income Tax Expense")
    da = _line(
        inc,
        "Depreciation And Amortization In Income Statement",
        "Depreciation And Amortization",
    )

    assets = _line(bs, "Total Assets")
    current_assets = _line(bs, "Current Assets", "Total Current Assets")
    current_liabilities = _line(bs, "Current Liabilities", "Total Current Liabilities")
    inventory = _line(bs, "Inventory") or 0
    cash = _line(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    debt = _line(bs, "Total Debt")
    equity = _line(bs, "Stockholders Equity", "Total Stockholder Equity")

    operating_cf = _line(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
    raw_capex = _line(cf, "Capital Expenditure", "Capital Expenditures")
    raw_reported_free_cf = _line(cf, "Free Cash Flow")
    change_nwc = _line(cf, "Change In Working Capital", "Change To Net Working Capital")
    statement_date = _statement_date(tk)
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

    market_cap = _n(info.get("marketCap"))
    enterprise_value = _n(info.get("enterpriseValue"))

    return {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": company.exchange,
        "currency": company.currency,
        "financial_currency": info.get("financialCurrency") or company.currency,
        "statement_date": statement_date,
        "captured_at": datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST"),
        # Fundamental / valuation
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "pe": _n(info.get("trailingPE")),
        "forward_pe": _n(info.get("forwardPE")),
        "price_to_book": _n(info.get("priceToBook")),
        "price_to_sales": _n(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _n(info.get("enterpriseToEbitda")),
        "dividend_yield": round(_n(info.get("dividendYield")) * 100, 2) if _n(info.get("dividendYield")) else None,
        # Profitability / returns
        "roe": _ratio(net_income, equity, True),
        "roa": _ratio(net_income, assets, True),
        "net_margin": _ratio(net_income, revenue, True),
        "operating_margin": _ratio(ebit, revenue, True),
        "ebitda_margin": _ratio(ebitda, revenue, True),
        # Leverage / liquidity
        "debt_to_equity": _ratio(debt, equity),
        "debt_to_assets": _ratio(debt, assets),
        "current_ratio": _ratio(current_assets, current_liabilities),
        "quick_ratio": _ratio((current_assets - inventory) if current_assets is not None else None, current_liabilities),
        "interest_coverage": _ratio(ebit, abs(interest) if interest else None),
        # Cash flow quality
        **cash_flow,
        "operating_cf_margin": _ratio(cash_flow["operating_cf"], revenue, True),
        "fcf_margin": _ratio(cash_flow["free_cf"], revenue, True),
        "fcff_margin": _ratio(cash_flow["fcff"], revenue, True),
        "cash_conversion": _ratio(cash_flow["operating_cf"], net_income),
        "capex_to_revenue": _ratio(cash_flow["capex"], revenue, True),
        # Growth / efficiency
        "revenue_growth": _growth(revenue, revenue_prev),
        "profit_growth": _growth(net_income, net_income_prev),
        "asset_turnover": _ratio(revenue, assets),
        # Important statement figures for context
        "revenue": revenue,
        "net_income": net_income,
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
            if row["statement_date"] == "N/A" or row["revenue"] is None:
                row = _company_ratios_fallback(company, formulas)
            await save_ratio_snapshot(row)
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            log.warning(f"yfinance ratio fetch failed for {company.ticker}: {e}")
            try:
                row = _company_ratios_fallback(company, formulas)
                await save_ratio_snapshot(row)
                rows.append(row)
            except Exception as fallback_error:  # noqa: BLE001
                log.error(f"ratio fallback failed for {company.ticker}: {fallback_error}")
                rows.append({
                    "name": company.name,
                    "ticker": company.ticker,
                    "exchange": company.exchange,
                    "currency": company.currency,
                    "financial_currency": company.currency,
                    "statement_date": "N/A",
                    "error": str(fallback_error),
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
