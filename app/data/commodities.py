"""Fetch commodity and index prices (gold, silver, oil, Nifty 50, S&P 500)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

log = logging.getLogger(__name__)

# Commodity / index tickers on Yahoo Finance
COMMODITY_TICKERS = {
    "gold": {"symbol": "GC=F", "name": "Gold (COMEX)", "unit": "$/oz"},
    "silver": {"symbol": "SI=F", "name": "Silver (COMEX)", "unit": "$/oz"},
    "crude_oil": {"symbol": "CL=F", "name": "Crude Oil (WTI)", "unit": "$/bbl"},
    "brent": {"symbol": "BZ=F", "name": "Brent Crude", "unit": "$/bbl"},
    "natural_gas": {"symbol": "NG=F", "name": "Natural Gas", "unit": "$/MMBtu"},
    "copper": {"symbol": "HG=F", "name": "Copper", "unit": "$/lb"},
}

INDEX_TICKERS = {
    "nifty50": {"symbol": "^NSEI", "name": "Nifty 50"},
    "sensex": {"symbol": "^BSESN", "name": "BSE Sensex"},
    "sp500": {"symbol": "^GSPC", "name": "S&P 500"},
    "nasdaq": {"symbol": "^IXIC", "name": "NASDAQ Composite"},
    "dowjones": {"symbol": "^DJI", "name": "Dow Jones"},
    "ftse100": {"symbol": "^FTSE", "name": "FTSE 100"},
}

# Gold/Silver in INR (MCX)
INDIAN_COMMODITY_TICKERS = {
    "gold_inr": {"symbol": "GOLDBEES.NS", "name": "Gold (India ETF)", "unit": "₹"},
    "silver_inr": {"symbol": "SILVERBEES.NS", "name": "Silver (India ETF)", "unit": "₹"},
}


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def _fetch_one(symbol: str, days_back: int = 400) -> dict:
    """Generic fetch for a single symbol returning price + changes."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=days_back)

    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(start=str(start), end=str(today + timedelta(days=1)))

        if hist.empty:
            return {"open": None, "close": None, "daily_change_pct": None,
                    "monthly_change_pct": None, "yearly_change_pct": None}

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else None
        monthly = hist.iloc[-23] if len(hist) >= 23 else hist.iloc[0]
        yearly = hist.iloc[-253] if len(hist) >= 253 else hist.iloc[0]

        close = _safe_float(latest.get("Close"))
        return {
            "open": _safe_float(latest.get("Open")),
            "close": close,
            "high": _safe_float(latest.get("High")),
            "low": _safe_float(latest.get("Low")),
            "prev_close": _safe_float(prev.get("Close")) if prev is not None else None,
            "daily_change_pct": _pct_change(close, _safe_float(prev.get("Close")) if prev is not None else None),
            "monthly_change_pct": _pct_change(close, _safe_float(monthly.get("Close"))),
            "yearly_change_pct": _pct_change(close, _safe_float(yearly.get("Close"))),
        }
    except Exception as e:
        log.error(f"Error fetching {symbol}: {e}")
        return {"open": None, "close": None, "daily_change_pct": None,
                "monthly_change_pct": None, "yearly_change_pct": None}


def fetch_commodities(is_weekend: bool = False) -> list[dict]:
    """Fetch commodity prices. Skip tradeable commodities on weekends."""
    results = []
    tickers = {**COMMODITY_TICKERS}
    if is_weekend:
        # Futures markets are closed on weekends – skip
        tickers = {}

    for key, meta in tickers.items():
        data = _fetch_one(meta["symbol"])
        results.append({
            "key": key,
            "name": meta["name"],
            "unit": meta.get("unit", ""),
            **data,
        })

    # Indian commodity ETFs
    if not is_weekend:
        for key, meta in INDIAN_COMMODITY_TICKERS.items():
            data = _fetch_one(meta["symbol"])
            results.append({
                "key": key,
                "name": meta["name"],
                "unit": meta.get("unit", "₹"),
                **data,
            })

    return results


def fetch_indices(is_weekend: bool = False) -> list[dict]:
    """Fetch major market indices."""
    results = []
    for key, meta in INDEX_TICKERS.items():
        if is_weekend:
            # Still show last known values; yfinance returns last trading day
            pass
        data = _fetch_one(meta["symbol"])
        results.append({
            "key": key,
            "name": meta["name"],
            **data,
        })
    return results
