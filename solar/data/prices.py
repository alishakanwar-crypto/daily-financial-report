"""Yesterday's open / close / average price for listed solar companies (IST)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import yfinance as yf

from solar.config import IST, Company, listed_companies

log = logging.getLogger(__name__)


class PossibleDelistingError(ValueError):
    pass


def _safe(v) -> Optional[float]:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def _average_price(tk: yf.Ticker, day) -> tuple[Optional[float], str]:
    """Best-effort average traded price for a given date.

    Tries intraday VWAP (sum(price*vol)/sum(vol)); falls back to the daily
    typical price (High+Low+Close)/3. Returns (value, method).
    """
    try:
        intraday = tk.history(
            start=str(day),
            end=str(day + timedelta(days=1)),
            interval="5m",
        )
        if not intraday.empty and intraday["Volume"].sum() > 0:
            typical = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
            vwap = float((typical * intraday["Volume"]).sum() / intraday["Volume"].sum())
            return round(vwap, 2), "VWAP (intraday 5m)"
    except Exception as e:  # noqa: BLE001
        log.debug(f"intraday avg failed: {e}")
    return None, "typical (H+L+C)/3"


def _chart_price(company: Company, now_ist: datetime) -> dict:
    start = int((now_ist - timedelta(days=10)).timestamp())
    end = int((now_ist + timedelta(days=1)).timestamp())
    response = httpx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{company.ticker}",
        params={
            "period1": start,
            "period2": end,
            "interval": "1d",
            "events": "div,splits",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        raise ValueError("Yahoo chart returned invalid JSON")
    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        description = error.get("description", "Yahoo chart error")
        normalized = description.lower()
        if "delisted" in normalized or "no data found" in normalized:
            raise PossibleDelistingError(description)
        raise ValueError(description)
    response.raise_for_status()
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo chart returned no result")
    result = results[0]
    quote = result["indicators"]["quote"][0]
    records = []

    def value(name: str, index: int) -> Optional[float]:
        values = quote.get(name, [])
        return _safe(values[index]) if index < len(values) else None

    for index, timestamp in enumerate(result.get("timestamp", [])):
        trade_date = datetime.fromtimestamp(timestamp, IST).date()
        if trade_date >= now_ist.date():
            continue
        close = value("close", index)
        if close is None:
            continue
        records.append({
            "date": trade_date,
            "open": value("open", index),
            "close": close,
            "high": value("high", index),
            "low": value("low", index),
            "volume": value("volume", index),
        })
    if not records:
        raise ValueError("Yahoo chart returned no completed trading days")

    last = records[-1]
    prev = records[-2] if len(records) >= 2 else None
    average = None
    if None not in (last["high"], last["low"], last["close"]):
        average = round((last["high"] + last["low"] + last["close"]) / 3, 2)
    return {
        "open": last["open"],
        "close": last["close"],
        "high": last["high"],
        "low": last["low"],
        "volume": last["volume"],
        "prev_close": prev["close"] if prev else None,
        "change_pct": _pct(last["close"], prev["close"] if prev else None),
        "trade_date": last["date"].strftime("%A, %d %B %Y"),
        "average": average,
        "avg_method": "typical (H+L+C)/3",
    }


def _usd_inr_rate(now_ist: datetime) -> tuple[Optional[float], Optional[str]]:
    start = int((now_ist - timedelta(days=10)).timestamp())
    end = int((now_ist + timedelta(days=1)).timestamp())
    last_error = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            response = httpx.get(
                f"https://{host}/v8/finance/chart/INR=X",
                params={
                    "period1": start,
                    "period2": end,
                    "interval": "1d",
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
            closes = result["indicators"]["quote"][0].get("close", [])
            records = []
            for index, timestamp in enumerate(result.get("timestamp", [])):
                date = datetime.fromtimestamp(timestamp, IST).date()
                rate = _safe(closes[index]) if index < len(closes) else None
                if date < now_ist.date() and rate is not None:
                    records.append((date, rate))
            if records:
                date, rate = records[-1]
                return rate, date.strftime("%d-%m-%Y")
        except Exception as e:  # noqa: BLE001
            last_error = e
    raise ValueError(f"USD/INR chart returned no completed trading day: {last_error}")


def fetch_prices(companies: Optional[list[Company]] = None) -> dict:
    """Return yesterday's OHLC + average for each listed company.

    "Yesterday" = the most recent completed trading day relative to now (IST).
    """
    now_ist = datetime.now(IST)
    rows = []
    trading_date_label = None
    usd_inr_rate = None
    usd_inr_date = None
    try:
        usd_inr_rate, usd_inr_date = _usd_inr_rate(now_ist)
    except Exception as e:  # noqa: BLE001
        log.error(f"USD/INR conversion fetch failed: {e}")

    for company in listed_companies(companies):
        row = {
            "name": company.name,
            "ticker": company.ticker,
            "currency": company.currency,
            "exchange": company.exchange,
            "symbol": "₹" if company.currency == "INR" else "$",
            "open": None,
            "close": None,
            "average": None,
            "avg_method": "",
            "high": None,
            "low": None,
            "volume": None,
            "prev_close": None,
            "change_pct": None,
            "trade_date": None,
            "delisting_signal": False,
        }
        try:
            tk = yf.Ticker(company.ticker)
            hist = tk.history(period="7d", interval="1d")
            if not hist.empty:
                completed = [i for i in hist.index if i.date() < now_ist.date()]
                if completed:
                    hist = hist.loc[completed]
            if hist.empty:
                raise ValueError("yfinance returned no completed trading days")
            last = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else None
            trade_date = hist.index[-1].date()

            row["open"] = _safe(last.get("Open"))
            row["close"] = _safe(last.get("Close"))
            row["high"] = _safe(last.get("High"))
            row["low"] = _safe(last.get("Low"))
            row["volume"] = _safe(last.get("Volume"))
            row["prev_close"] = _safe(prev.get("Close")) if prev is not None else None
            row["change_pct"] = _pct(row["close"], row["prev_close"])
            row["trade_date"] = trade_date.strftime("%A, %d %B %Y")

            avg, method = _average_price(tk, trade_date)
            if avg is None:
                high, low, close = row["high"], row["low"], row["close"]
                if None not in (high, low, close):
                    avg = round((high + low + close) / 3, 2)
            row["average"] = avg
            row["avg_method"] = method
            if trading_date_label is None:
                trading_date_label = row["trade_date"]
        except Exception as e:  # noqa: BLE001
            log.warning(f"yfinance price fetch failed for {company.ticker}: {e}")
        if row["close"] is None:
            try:
                row.update(_chart_price(company, now_ist))
                if trading_date_label is None:
                    trading_date_label = row["trade_date"]
            except PossibleDelistingError as e:
                row["delisting_signal"] = True
                row["listing_error"] = str(e)
                log.warning(
                    "Possible delisting signal for %s: %s",
                    company.ticker,
                    e,
                )
            except Exception as e:  # noqa: BLE001
                log.error(f"Yahoo chart fallback failed for {company.ticker}: {e}")
        rows.append(row)

    return {
        "generated_at": now_ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "trading_date": trading_date_label or "N/A",
        "usd_inr_rate": usd_inr_rate,
        "usd_inr_date": usd_inr_date,
        "rows": rows,
    }
