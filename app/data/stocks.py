"""Fetch stock data, DuPont ratios, and financial metrics via yfinance."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

log = logging.getLogger(__name__)

# Human-readable names for tickers
TICKER_NAMES: dict[str, str] = {
    # Indian
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "INFY.NS": "Infosys",
    "ICICIBANK.NS": "ICICI Bank",
    "BHARTIARTL.NS": "Bharti Airtel",
    "SBIN.NS": "State Bank of India",
    "ITC.NS": "ITC Limited",
    "LT.NS": "Larsen & Toubro",
    "AXISBANK.NS": "Axis Bank",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "SUNPHARMA.NS": "Sun Pharmaceutical",
    "ADANIENT.NS": "Adani Enterprises",
    "BAJFINANCE.NS": "Bajaj Finance",
    # US
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet (Google)",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "BRK-B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase",
    "JNJ": "Johnson & Johnson",
    "V": "Visa",
    "UNH": "UnitedHealth",
    "WMT": "Walmart",
    "LLY": "Eli Lilly",
    "MA": "Mastercard",
}


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if v != v else v  # NaN check
    except (TypeError, ValueError):
        return None


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def _format_market_cap(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1e12:
        return f"${val / 1e12:.2f}T"
    if val >= 1e9:
        return f"${val / 1e9:.2f}B"
    if val >= 1e6:
        return f"${val / 1e6:.2f}M"
    return f"${val:,.0f}"


def _format_market_cap_inr(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1e12:
        return f"₹{val / 1e12:.2f}T"
    if val >= 1e9:
        return f"₹{val / 1e9:.2f}B"
    if val >= 1e7:
        return f"₹{val / 1e7:.2f}Cr"
    return f"₹{val:,.0f}"


def fetch_stock_data(tickers: list[str], currency: str = "USD") -> list[dict]:
    """Fetch price data, market cap, and DuPont ratios for a list of tickers."""
    results = []
    today = datetime.utcnow().date()
    # Get enough history for monthly/yearly comparisons
    start_date = today - timedelta(days=400)

    for ticker_symbol in tickers:
        try:
            tk = yf.Ticker(ticker_symbol)
            hist = tk.history(start=str(start_date), end=str(today + timedelta(days=1)))

            if hist.empty or len(hist) < 2:
                log.warning(f"No data for {ticker_symbol}")
                results.append(_empty_stock(ticker_symbol, currency))
                continue

            # Yesterday and day before
            yesterday = hist.iloc[-1]
            day_before = hist.iloc[-2] if len(hist) >= 2 else None

            # Monthly comparison (~22 trading days)
            monthly_row = hist.iloc[-23] if len(hist) >= 23 else hist.iloc[0]
            # Yearly comparison (~252 trading days)
            yearly_row = hist.iloc[-253] if len(hist) >= 253 else hist.iloc[0]

            open_price = _safe_float(yesterday.get("Open"))
            close_price = _safe_float(yesterday.get("Close"))
            day_before_close = _safe_float(day_before.get("Close")) if day_before is not None else None

            info = tk.info or {}
            market_cap = _safe_float(info.get("marketCap"))
            fmt_cap = _format_market_cap_inr(market_cap) if currency == "INR" else _format_market_cap(market_cap)

            # DuPont ratios
            dupont = _compute_dupont(tk)

            row = {
                "ticker": ticker_symbol,
                "name": TICKER_NAMES.get(ticker_symbol, info.get("shortName", ticker_symbol)),
                "currency": currency,
                "market_cap": market_cap,
                "market_cap_fmt": fmt_cap,
                "open": open_price,
                "close": close_price,
                "day_before_close": day_before_close,
                "daily_change_pct": _pct_change(close_price, day_before_close),
                "monthly_change_pct": _pct_change(close_price, _safe_float(monthly_row.get("Close"))),
                "yearly_change_pct": _pct_change(close_price, _safe_float(yearly_row.get("Close"))),
                "volume": _safe_float(yesterday.get("Volume")),
                "high": _safe_float(yesterday.get("High")),
                "low": _safe_float(yesterday.get("Low")),
                **dupont,
            }
            results.append(row)
        except Exception as e:
            log.error(f"Error fetching {ticker_symbol}: {e}")
            results.append(_empty_stock(ticker_symbol, currency))

    return results


def _compute_dupont(tk: yf.Ticker) -> dict:
    """Compute full DuPont decomposition from financial statements."""
    blank = {
        "roe": None,
        "net_profit_margin": None,
        "asset_turnover": None,
        "equity_multiplier": None,
        "tax_burden": None,
        "interest_burden": None,
        "operating_margin": None,
    }
    try:
        inc = tk.income_stmt
        bs = tk.balance_sheet
        if inc is None or bs is None or inc.empty or bs.empty:
            return blank

        # Most recent annual figures (first column)
        net_income = _safe_float(inc.loc["Net Income"].iloc[0]) if "Net Income" in inc.index else None
        revenue = _safe_float(inc.loc["Total Revenue"].iloc[0]) if "Total Revenue" in inc.index else None
        ebit = _safe_float(inc.loc["EBIT"].iloc[0]) if "EBIT" in inc.index else None
        pretax = _safe_float(inc.loc["Pretax Income"].iloc[0]) if "Pretax Income" in inc.index else None

        total_assets = _safe_float(bs.loc["Total Assets"].iloc[0]) if "Total Assets" in bs.index else None
        equity_key = "Stockholders Equity"
        if equity_key not in bs.index:
            equity_key = "Total Stockholder Equity"
        if equity_key not in bs.index:
            # Try common variants
            for k in bs.index:
                if "stockholder" in k.lower() and "equity" in k.lower():
                    equity_key = k
                    break
        total_equity = _safe_float(bs.loc[equity_key].iloc[0]) if equity_key in bs.index else None

        # 3-part DuPont
        npm = (net_income / revenue * 100) if net_income and revenue else None
        at = (revenue / total_assets) if revenue and total_assets else None
        em = (total_assets / total_equity) if total_assets and total_equity else None
        roe = (net_income / total_equity * 100) if net_income and total_equity else None

        # 5-part DuPont
        tax_burden = (net_income / pretax) if net_income and pretax else None
        interest_burden = (pretax / ebit) if pretax and ebit else None
        op_margin = (ebit / revenue * 100) if ebit and revenue else None

        return {
            "roe": round(roe, 2) if roe else None,
            "net_profit_margin": round(npm, 2) if npm else None,
            "asset_turnover": round(at, 2) if at else None,
            "equity_multiplier": round(em, 2) if em else None,
            "tax_burden": round(tax_burden, 2) if tax_burden else None,
            "interest_burden": round(interest_burden, 2) if interest_burden else None,
            "operating_margin": round(op_margin, 2) if op_margin else None,
        }
    except Exception as e:
        log.debug(f"DuPont calc error: {e}")
        return blank


def _empty_stock(ticker: str, currency: str) -> dict:
    return {
        "ticker": ticker,
        "name": TICKER_NAMES.get(ticker, ticker),
        "currency": currency,
        "market_cap": None,
        "market_cap_fmt": "N/A",
        "open": None,
        "close": None,
        "day_before_close": None,
        "daily_change_pct": None,
        "monthly_change_pct": None,
        "yearly_change_pct": None,
        "volume": None,
        "high": None,
        "low": None,
        "roe": None,
        "net_profit_margin": None,
        "asset_turnover": None,
        "equity_multiplier": None,
        "tax_burden": None,
        "interest_burden": None,
        "operating_margin": None,
    }
