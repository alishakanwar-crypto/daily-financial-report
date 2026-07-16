"""Official exchange price history and official USD/INR reference rates."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from solar.config import DEFAULT_COMPANIES, Company, IST, listed_companies

log = logging.getLogger(__name__)

NASDAQ_HISTORY_API = "https://api.nasdaq.com/api/quote/RNW/historical"
NASDAQ_HISTORY_PAGE = "https://www.nasdaq.com/market-activity/stocks/rnw/historical"
BSE_HISTORY_PAGE = (
    "https://beta.bseindia.com/markets/equity/EQReports/"
    "StockPrcHistori.aspx"
)
BSE_GRAPH_API = "https://api.bseindia.com/BseIndiaAPI/api/StockReachGraph/w"
FBIL_REFERENCE_RATE_API = (
    "https://www.fbil.org.in/wasdm/refrates/fetch?authenticated=false"
)

OFFICIAL_MARKET_REGISTRY: dict[str, dict[str, str]] = {
    "RNW": {
        "adapter": "nasdaq",
        "exchange": "NASDAQ",
        "official_symbol": "RNW",
        "source_name": "Nasdaq official historical prices",
        "source_url": NASDAQ_HISTORY_PAGE,
    },
    "WAAREEENER.NS": {
        "adapter": "bse",
        "exchange": "BSE",
        "official_symbol": "WAAREEENER",
        "bse_scrip_code": "544277",
        "source_name": "BSE official historical prices",
    },
    "PREMIERENE.NS": {
        "adapter": "bse",
        "exchange": "BSE",
        "official_symbol": "PREMIERENE",
        "bse_scrip_code": "544238",
        "source_name": "BSE official historical prices",
    },
    "VIKRAMSOLR.NS": {
        "adapter": "bse",
        "exchange": "BSE",
        "official_symbol": "VIKRAMSOLR",
        "bse_scrip_code": "544488",
        "source_name": "BSE official historical prices",
    },
    "EMMVEE.NS": {
        "adapter": "bse",
        "exchange": "BSE",
        "official_symbol": "EMMVEE",
        "bse_scrip_code": "544608",
        "source_name": "BSE official historical prices",
    },
}


def _headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    }


def _float(value) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    if cleaned in {"", "-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _integer(value) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _movement(first: float | None, last: float | None) -> float | None:
    if first in (None, 0) or last is None:
        return None
    return round((last - first) / first * 100, 2)


def _line_chart(
    points: list[dict],
    *,
    title: str,
    width: int = 520,
    height: int = 150,
) -> str:
    valid = [point for point in points if point.get("close") is not None]
    if len(valid) < 2:
        return ""
    values = [float(point["close"]) for point in valid]
    low = min(values)
    high = max(values)
    span = high - low or 1
    pad_x = 20
    pad_y = 24
    plot_width = width - pad_x * 2
    plot_height = height - pad_y * 2
    coordinates = []
    for index, value in enumerate(values):
        x = pad_x + index / (len(values) - 1) * plot_width
        y = pad_y + (high - value) / span * plot_height
        coordinates.append(f"{x:.1f},{y:.1f}")
    first_label = escape(valid[0]["date"].strftime("%d-%m-%Y"))
    last_label = escape(valid[-1]["date"].strftime("%d-%m-%Y"))
    change = _movement(values[0], values[-1])
    change_label = "N/A" if change is None else f"{change:+.2f}%"
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(title)}">'
        f'<rect width="{width}" height="{height}" rx="10" fill="#f3fbf6"/>'
        f'<text x="20" y="18" font-size="12" fill="#075f36">{escape(title)}</text>'
        f'<polyline fill="none" stroke="#16a36a" stroke-width="3" '
        f'points="{" ".join(coordinates)}"/>'
        f'<circle cx="{coordinates[-1].split(",")[0]}" '
        f'cy="{coordinates[-1].split(",")[1]}" r="4" fill="#075f36"/>'
        f'<text x="20" y="{height - 6}" font-size="10" fill="#52665c">'
        f'{first_label}</text>'
        f'<text x="{width - 20}" y="{height - 6}" text-anchor="end" '
        f'font-size="10" fill="#52665c">{last_label} • {change_label}</text>'
        "</svg>"
    )


def _ohlc_chart(row: dict, *, width: int = 260, height: int = 150) -> str:
    values = [row.get(key) for key in ("open", "high", "low", "close")]
    if any(value is None for value in values):
        return ""
    low = float(row["low"])
    high = float(row["high"])
    span = high - low or 1
    top = 28
    bottom = height - 28

    def y(value: float) -> float:
        return top + (high - value) / span * (bottom - top)

    open_y = y(float(row["open"]))
    close_y = y(float(row["close"]))
    high_y = y(high)
    low_y = y(low)
    average = row.get("average")
    average_line = ""
    if average is not None:
        average_y = y(float(average))
        average_line = (
            f'<line x1="35" x2="{width - 35}" y1="{average_y:.1f}" '
            f'y2="{average_y:.1f}" stroke="#89b8a0" stroke-dasharray="4 3"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="OHLC for {escape(row["trade_date"])}">'
        f'<rect width="{width}" height="{height}" rx="10" fill="#f3fbf6"/>'
        f'<text x="16" y="18" font-size="12" fill="#075f36">'
        f'Completed session {escape(row["trade_date"])}</text>'
        f'{average_line}'
        f'<line x1="{width / 2}" x2="{width / 2}" y1="{high_y:.1f}" '
        f'y2="{low_y:.1f}" stroke="#075f36" stroke-width="3"/>'
        f'<line x1="{width / 2 - 30}" x2="{width / 2}" '
        f'y1="{open_y:.1f}" y2="{open_y:.1f}" stroke="#16a36a" stroke-width="4"/>'
        f'<line x1="{width / 2}" x2="{width / 2 + 30}" '
        f'y1="{close_y:.1f}" y2="{close_y:.1f}" stroke="#d97706" stroke-width="4"/>'
        f'<text x="16" y="{height - 8}" font-size="10" fill="#52665c">'
        f'O {row["open"]:.2f} • H {high:.2f} • L {low:.2f} • '
        f'C {row["close"]:.2f}</text>'
        "</svg>"
    )


def _parse_nasdaq_rows(payload: dict) -> list[dict]:
    table = (payload.get("data") or {}).get("tradesTable") or {}
    parsed = []
    for row in table.get("rows") or []:
        try:
            session_date = datetime.strptime(row["date"], "%m/%d/%Y").date()
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append({
            "date": session_date,
            "open": _float(row.get("open")),
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "close": _float(row.get("close")),
            "volume": _integer(row.get("volume")),
            "average": None,
        })
    return sorted(parsed, key=lambda item: item["date"])


def _parse_bse_history(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    parsed = []
    for row in soup.select("tr.TTRow"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 7:
            continue
        try:
            session_date = datetime.strptime(cells[0], "%d/%m/%y").date()
        except ValueError:
            continue
        parsed.append({
            "date": session_date,
            "open": _float(cells[1]),
            "high": _float(cells[2]),
            "low": _float(cells[3]),
            "close": _float(cells[4]),
            "average": _float(cells[5]),
            "volume": _integer(cells[6]),
        })
    return sorted(parsed, key=lambda item: item["date"])


def _parse_bse_graph(payload: dict) -> list[dict]:
    data = payload.get("Data")
    if not data:
        return []
    entries = json.loads(data) if isinstance(data, str) else data
    parsed = []
    for entry in entries:
        try:
            session_date = datetime.strptime(
                entry["dttm"],
                "%a %b %d %Y %H:%M:%S",
            ).date()
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append({
            "date": session_date,
            "close": _float(entry.get("vale1")),
            "volume": _integer(entry.get("vole")),
        })
    return sorted(parsed, key=lambda item: item["date"])


def _completed(rows: list[dict], today: date) -> list[dict]:
    return [row for row in rows if row["date"] < today and row.get("close") is not None]


def _price_row(
    company: Company,
    metadata: dict,
    summary_rows: list[dict],
    chart_rows: list[dict],
    chart_source_url: str,
    today: date,
) -> dict:
    completed_summary = _completed(summary_rows, today)
    completed_chart = _completed(chart_rows, today)
    if not completed_summary:
        raise ValueError("Official exchange feed returned no completed trading session")
    latest = completed_summary[-1]
    if latest["average"] is None:
        latest["average"] = round(
            (latest["high"] + latest["low"] + latest["close"]) / 3,
            4,
        )
        average_method = "Derived typical price: (High + Low + Close) / 3"
    else:
        average_method = "Official exchange WAP"
    week = completed_chart[-5:]
    year_cutoff = today - timedelta(days=366)
    year = [point for point in completed_chart if point["date"] >= year_cutoff]
    source_url = metadata["source_url"]
    row = {
        "name": company.name,
        "ticker": company.ticker,
        "exchange": metadata["exchange"],
        "official_symbol": metadata["official_symbol"],
        "currency": company.currency,
        "symbol": "₹" if company.currency == "INR" else "$",
        "trade_date": latest["date"].strftime("%d-%m-%Y"),
        "open": latest["open"],
        "close": latest["close"],
        "average": latest["average"],
        "average_method": average_method,
        "high": latest["high"],
        "low": latest["low"],
        "volume": latest["volume"],
        "change_pct": _movement(latest["open"], latest["close"]),
        "source_name": metadata["source_name"],
        "source_url": source_url,
        "chart_source_url": chart_source_url,
        "source_classification": "Official exchange/ticker feed",
        "delisting_signal": False,
        "daily_chart_svg": "",
        "weekly_chart_svg": _line_chart(week, title="Five completed sessions"),
        "yearly_chart_svg": _line_chart(year, title="One-year completed closes"),
        "weekly_change_pct": _movement(
            week[0]["close"] if week else None,
            week[-1]["close"] if week else None,
        ),
        "yearly_change_pct": _movement(
            year[0]["close"] if year else None,
            year[-1]["close"] if year else None,
        ),
        "weekly_points": week,
        "yearly_points": year,
    }
    row["daily_chart_svg"] = _ohlc_chart(row)
    return row


def _fetch_nasdaq(company: Company, metadata: dict, today: date) -> dict:
    params = {
        "assetclass": "stocks",
        "fromdate": (today - timedelta(days=366)).isoformat(),
        "limit": 500,
    }
    with httpx.Client(timeout=30, headers=_headers("https://www.nasdaq.com/")) as client:
        response = client.get(NASDAQ_HISTORY_API, params=params)
        response.raise_for_status()
    rows = _parse_nasdaq_rows(response.json())
    chart_url = f"{NASDAQ_HISTORY_API}?{urlencode(params)}"
    return _price_row(company, metadata, rows, rows, chart_url, today)


def _bse_urls(scrip_code: str) -> tuple[str, str]:
    history_params = {
        "Submit": "G",
        "expandable": "7",
        "flag": "sp",
        "scripcode": scrip_code,
    }
    graph_params = {
        "scripcode": scrip_code,
        "flag": "12M",
        "fromdate": "",
        "todate": "",
        "seriesid": "",
    }
    return (
        f"{BSE_HISTORY_PAGE}?{urlencode(history_params)}",
        f"{BSE_GRAPH_API}?{urlencode(graph_params)}",
    )


def _fetch_bse(company: Company, metadata: dict, today: date) -> dict:
    history_url, graph_url = _bse_urls(metadata["bse_scrip_code"])
    metadata = {**metadata, "source_url": history_url}
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers=_headers("https://www.bseindia.com/"),
    ) as client:
        history_response = client.get(history_url)
        history_response.raise_for_status()
        graph_response = client.get(graph_url)
        graph_response.raise_for_status()
    summary_rows = _parse_bse_history(history_response.text)
    chart_rows = _parse_bse_graph(graph_response.json())
    return _price_row(
        company,
        metadata,
        summary_rows,
        chart_rows,
        graph_url,
        today,
    )


def _fetch_usd_inr(today: date) -> dict:
    try:
        response = httpx.get(
            FBIL_REFERENCE_RATE_API,
            headers=_headers("https://www.fbil.org.in/"),
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("FBIL returned an unexpected response shape")
        candidates = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("subProdName") != "INR / 1 USD":
                continue
            process_date = datetime.strptime(
                item["processRunDate"],
                "%Y-%m-%d %H:%M:%S",
            ).date()
            if process_date <= today:
                candidates.append((process_date, float(item["rate"])))
        if not candidates:
            raise ValueError("FBIL returned no current INR / 1 USD reference rate")
        rate_date, rate = max(candidates, key=lambda item: item[0])
        return {
            "rate": rate,
            "date": rate_date.strftime("%d-%m-%Y"),
            "source_name": "FBIL USD/INR reference rate",
            "source_url": FBIL_REFERENCE_RATE_API,
            "error": None,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("official FBIL USD/INR fetch failed: %s", exc)
        return {
            "rate": None,
            "date": None,
            "source_name": "FBIL USD/INR reference rate",
            "source_url": FBIL_REFERENCE_RATE_API,
            "error": str(exc),
        }


def fetch_prices(companies: list[Company] | None = None) -> dict:
    """Return official completed-session prices and daily/weekly/yearly charts."""
    source = companies if companies is not None else DEFAULT_COMPANIES
    now_ist = datetime.now(IST)
    today = now_ist.date()
    rows = []
    for company in listed_companies(source):
        metadata = OFFICIAL_MARKET_REGISTRY.get(company.ticker)
        if metadata is None:
            rows.append({
                "name": company.name,
                "ticker": company.ticker,
                "exchange": company.exchange,
                "currency": company.currency,
                "symbol": "₹" if company.currency == "INR" else "$",
                "trade_date": "Unavailable",
                "open": None,
                "close": None,
                "average": None,
                "high": None,
                "low": None,
                "volume": None,
                "change_pct": None,
                "source_url": company.website,
                "source_name": "Official exchange adapter unavailable",
                "source_classification": "Unavailable",
                "error": (
                    "No official ticker/exchange adapter is configured; no secondary "
                    "market source was substituted."
                ),
                "delisting_signal": False,
            })
            continue
        try:
            if metadata["adapter"] == "nasdaq":
                row = _fetch_nasdaq(company, metadata, today)
            elif metadata["adapter"] == "bse":
                row = _fetch_bse(company, metadata, today)
            else:
                raise ValueError("Unknown official market adapter")
            rows.append(row)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            log.warning("official price fetch failed for %s: %s", company.ticker, exc)
            source_url = metadata.get("source_url", company.website)
            if metadata["adapter"] == "bse":
                source_url = _bse_urls(metadata["bse_scrip_code"])[0]
            rows.append({
                "name": company.name,
                "ticker": company.ticker,
                "exchange": metadata["exchange"],
                "currency": company.currency,
                "symbol": "₹" if company.currency == "INR" else "$",
                "trade_date": "Unavailable",
                "open": None,
                "close": None,
                "average": None,
                "high": None,
                "low": None,
                "volume": None,
                "change_pct": None,
                "source_url": source_url,
                "source_name": metadata["source_name"],
                "source_classification": "Official exchange/ticker feed",
                "error": str(exc),
                "delisting_signal": False,
            })

    fx = _fetch_usd_inr(today)
    completed_dates = [
        row["trade_date"]
        for row in rows
        if row.get("close") is not None
    ]
    return {
        "trading_date": (
            f"Latest completed sessions: {', '.join(sorted(set(completed_dates)))}"
            if completed_dates
            else "Official completed-session prices unavailable"
        ),
        "generated_at": now_ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "rows": rows,
        "usd_inr_rate": fx["rate"],
        "usd_inr_date": fx["date"],
        "usd_inr_source_name": fx["source_name"],
        "usd_inr_source_url": fx["source_url"],
        "usd_inr_error": fx["error"],
        "market_source_policy": (
            "Official Nasdaq/BSE ticker and exchange feeds only; no secondary market "
            "source or silent fallback."
        ),
    }
