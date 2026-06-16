"""Fetch commodity and index prices (gold, silver, oil, Nifty 50, S&P 500)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd

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


def _batch_download(symbols: list[str], period: str = "1y") -> pd.DataFrame:
    """Download history for multiple symbols in one call with retries."""
    for attempt in range(3):
        try:
            df = yf.download(
                symbols,
                period=period,
                group_by="ticker",
                threads=False,
                progress=False,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            log.warning(f"Batch download attempt {attempt + 1} failed: {e}")
        time.sleep(2 * (attempt + 1))
    return pd.DataFrame()


def _extract_metrics(df: pd.DataFrame, symbol: str, multi_ticker: bool) -> dict:
    """Extract price and change metrics for a single symbol from batch data."""
    empty = {"open": None, "close": None, "high": None, "low": None,
             "prev_close": None, "daily_change_pct": None,
             "monthly_change_pct": None, "yearly_change_pct": None}
    try:
        if df.empty:
            return empty

        if multi_ticker:
            try:
                hist = df[symbol].dropna(how="all")
            except KeyError:
                return empty
        else:
            hist = df

        if hist.empty:
            return empty

        # Skip today's partial data if the latest row has NaN close
        if pd.isna(hist.iloc[-1].get("Close")):
            hist = hist.iloc[:-1]
        if hist.empty:
            return empty

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
        log.error(f"Error extracting metrics for {symbol}: {e}")
        return empty


def fetch_commodities(is_weekend: bool = False) -> list[dict]:
    """Fetch commodity prices. Skip tradeable commodities on weekends."""
    if is_weekend:
        return []

    tickers = {**COMMODITY_TICKERS, **INDIAN_COMMODITY_TICKERS}
    symbols = [meta["symbol"] for meta in tickers.values()]

    log.info(f"Batch downloading {len(symbols)} commodity tickers...")
    df = _batch_download(symbols, period="1y")
    multi = len(symbols) > 1

    results = []
    for key, meta in tickers.items():
        data = _extract_metrics(df, meta["symbol"], multi)
        results.append({
            "key": key,
            "name": meta["name"],
            "unit": meta.get("unit", ""),
            **data,
        })
    return results


def fetch_indices(is_weekend: bool = False) -> list[dict]:
    """Fetch major market indices."""
    symbols = [meta["symbol"] for meta in INDEX_TICKERS.values()]

    log.info(f"Batch downloading {len(symbols)} index tickers...")
    df = _batch_download(symbols, period="1y")
    multi = len(symbols) > 1

    results = []
    for key, meta in INDEX_TICKERS.items():
        data = _extract_metrics(df, meta["symbol"], multi)
        results.append({
            "key": key,
            "name": meta["name"],
            **data,
        })
    return results
