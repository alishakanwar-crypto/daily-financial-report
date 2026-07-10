"""Comparative financial, fundamental, cash-flow, and operating ratios."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

import yfinance as yf

from solar.config import COMPANIES, Company, IST, listed_companies
from solar.database import save_ratio_snapshot

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


def _company_ratios(company: Company) -> dict:
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

    assets = _line(bs, "Total Assets")
    current_assets = _line(bs, "Current Assets", "Total Current Assets")
    current_liabilities = _line(bs, "Current Liabilities", "Total Current Liabilities")
    inventory = _line(bs, "Inventory") or 0
    cash = _line(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    debt = _line(bs, "Total Debt")
    equity = _line(bs, "Stockholders Equity", "Total Stockholder Equity")

    operating_cf = _line(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
    capex = _line(cf, "Capital Expenditure", "Capital Expenditures")
    free_cf = _line(cf, "Free Cash Flow")
    if free_cf is None and operating_cf is not None and capex is not None:
        free_cf = operating_cf + capex  # yfinance capex is usually negative

    market_cap = _n(info.get("marketCap"))
    enterprise_value = _n(info.get("enterpriseValue"))

    return {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": company.exchange,
        "currency": company.currency,
        "statement_date": _statement_date(tk),
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
        "operating_cf": operating_cf,
        "free_cf": free_cf,
        "operating_cf_margin": _ratio(operating_cf, revenue, True),
        "fcf_margin": _ratio(free_cf, revenue, True),
        "cash_conversion": _ratio(operating_cf, net_income),
        "capex_to_revenue": _ratio(abs(capex) if capex else None, revenue, True),
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


async def fetch_and_store_ratios() -> list[dict]:
    """Fetch current ratios and upsert one snapshot per statement date."""
    rows = []
    for company in listed_companies():
        try:
            row = _company_ratios(company)
            await save_ratio_snapshot(row)
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            log.error(f"ratio fetch failed for {company.ticker}: {e}")
            rows.append({
                "name": company.name,
                "ticker": company.ticker,
                "exchange": company.exchange,
                "currency": company.currency,
                "statement_date": "N/A",
                "error": str(e),
            })
    # Include unlisted company explicitly to avoid implying missing coverage.
    for company in COMPANIES:
        if not company.listed:
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
