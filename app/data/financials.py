"""Select a deep-dive company and locate annual report / 10-K links."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")

log = logging.getLogger(__name__)

# Pool of top companies for deep dive rotation
INDIAN_DEEP_DIVE_POOL = [
    ("RELIANCE.NS", "Reliance Industries", "https://www.bseindia.com/stock-share-price/reliance-industries-ltd/reliance/500325/"),
    ("TCS.NS", "Tata Consultancy Services", "https://www.bseindia.com/stock-share-price/tata-consultancy-services-ltd/tcs/532540/"),
    ("HDFCBANK.NS", "HDFC Bank", "https://www.bseindia.com/stock-share-price/hdfc-bank-ltd/hdfcbank/500180/"),
    ("INFY.NS", "Infosys", "https://www.bseindia.com/stock-share-price/infosys-ltd/infy/500209/"),
    ("ICICIBANK.NS", "ICICI Bank", "https://www.bseindia.com/stock-share-price/icici-bank-ltd/icicibank/532174/"),
    ("BHARTIARTL.NS", "Bharti Airtel", "https://www.bseindia.com/stock-share-price/bharti-airtel-ltd/bhartiartl/532454/"),
    ("ITC.NS", "ITC Limited", "https://www.bseindia.com/stock-share-price/itc-ltd/itc/500875/"),
    ("LT.NS", "Larsen & Toubro", "https://www.bseindia.com/stock-share-price/larsen-and-toubro-ltd/lt/500510/"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical", "https://www.bseindia.com/stock-share-price/sun-pharmaceutical-industries-ltd/sunpharma/524715/"),
    ("ADANIENT.NS", "Adani Enterprises", "https://www.bseindia.com/stock-share-price/adani-enterprises-ltd/adanient/512599/"),
]

US_DEEP_DIVE_POOL = [
    ("AAPL", "Apple Inc.", "https://investor.apple.com/sec-filings/default.aspx"),
    ("MSFT", "Microsoft Corporation", "https://www.microsoft.com/en-us/Investor/sec-filings.aspx"),
    ("NVDA", "NVIDIA Corporation", "https://investor.nvidia.com/financial-info/sec-filings"),
    ("AMZN", "Amazon.com Inc.", "https://ir.aboutamazon.com/sec-filings/default.aspx"),
    ("GOOGL", "Alphabet Inc.", "https://abc.xyz/investor/"),
    ("META", "Meta Platforms Inc.", "https://investor.fb.com/financials/sec-filings/default.aspx"),
    ("TSLA", "Tesla Inc.", "https://ir.tesla.com/sec-filings"),
    ("JPM", "JPMorgan Chase & Co.", "https://www.jpmorganchase.com/ir/sec-filings"),
    ("JNJ", "Johnson & Johnson", "https://www.investor.jnj.com/sec-filings"),
    ("BRK-B", "Berkshire Hathaway", "https://www.berkshirehathaway.com/reports.html"),
]


def _get_financials_summary(ticker_symbol: str) -> dict:
    """Pull key annual financials from yfinance."""
    try:
        tk = yf.Ticker(ticker_symbol)
        inc = tk.income_stmt
        bs = tk.balance_sheet
        cf = tk.cashflow

        def _val(df, key):
            if df is not None and not df.empty and key in df.index:
                v = df.loc[key].iloc[0]
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            return None

        return {
            "revenue": _val(inc, "Total Revenue"),
            "net_income": _val(inc, "Net Income"),
            "ebitda": _val(inc, "EBITDA"),
            "total_assets": _val(bs, "Total Assets"),
            "total_debt": _val(bs, "Total Debt"),
            "operating_cashflow": _val(cf, "Operating Cash Flow"),
            "free_cashflow": _val(cf, "Free Cash Flow"),
            "fiscal_year_end": tk.info.get("lastFiscalYearEnd"),
        }
    except Exception as e:
        log.error(f"Error fetching financials for {ticker_symbol}: {e}")
        return {}


def _fmt_big(val, prefix="$"):
    if val is None:
        return "N/A"
    sign = "-" if val < 0 else ""
    val = abs(val)
    if val >= 1e12:
        return f"{sign}{prefix}{val/1e12:.2f}T"
    if val >= 1e9:
        return f"{sign}{prefix}{val/1e9:.2f}B"
    if val >= 1e6:
        return f"{sign}{prefix}{val/1e6:.2f}M"
    return f"{sign}{prefix}{val:,.0f}"


def select_deep_dive() -> dict:
    """Pick one Indian and one US company for today's deep dive."""
    day_of_year = datetime.now(IST).timetuple().tm_yday
    indian_idx = day_of_year % len(INDIAN_DEEP_DIVE_POOL)
    us_idx = day_of_year % len(US_DEEP_DIVE_POOL)

    ind_ticker, ind_name, ind_filing_url = INDIAN_DEEP_DIVE_POOL[indian_idx]
    us_ticker, us_name, us_filing_url = US_DEEP_DIVE_POOL[us_idx]

    ind_fin = _get_financials_summary(ind_ticker)
    us_fin = _get_financials_summary(us_ticker)

    prefix_ind = "₹"
    prefix_us = "$"

    return {
        "indian": {
            "ticker": ind_ticker,
            "name": ind_name,
            "filing_url": ind_filing_url,
            "sec_url": f"https://www.bseindia.com/corporates/ann.html?scrip={ind_ticker.replace('.NS', '')}",
            "revenue": _fmt_big(ind_fin.get("revenue"), prefix_ind),
            "net_income": _fmt_big(ind_fin.get("net_income"), prefix_ind),
            "ebitda": _fmt_big(ind_fin.get("ebitda"), prefix_ind),
            "total_assets": _fmt_big(ind_fin.get("total_assets"), prefix_ind),
            "total_debt": _fmt_big(ind_fin.get("total_debt"), prefix_ind),
            "operating_cashflow": _fmt_big(ind_fin.get("operating_cashflow"), prefix_ind),
            "free_cashflow": _fmt_big(ind_fin.get("free_cashflow"), prefix_ind),
        },
        "us": {
            "ticker": us_ticker,
            "name": us_name,
            "filing_url": us_filing_url,
            "sec_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={us_ticker}&type=10-K&dateb=&owner=include&count=5",
            "revenue": _fmt_big(us_fin.get("revenue"), prefix_us),
            "net_income": _fmt_big(us_fin.get("net_income"), prefix_us),
            "ebitda": _fmt_big(us_fin.get("ebitda"), prefix_us),
            "total_assets": _fmt_big(us_fin.get("total_assets"), prefix_us),
            "total_debt": _fmt_big(us_fin.get("total_debt"), prefix_us),
            "operating_cashflow": _fmt_big(us_fin.get("operating_cashflow"), prefix_us),
            "free_cashflow": _fmt_big(us_fin.get("free_cashflow"), prefix_us),
        },
    }
