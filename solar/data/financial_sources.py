"""Authoritative cash-flow sources and current official input cross-checks."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from solar.config import IST


OFFICIAL_CASH_FLOW_SOURCES: dict[str, dict] = {
    "RNW": {
        "source_name": "ReNew FY26 results (SEC Form 6-K, Exhibit 99.1)",
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1848763/"
            "000119312526227847/rnw-ex99_1.htm"
        ),
        "source_type": "Official SEC filing",
        "statement_date": "31-03-2026",
        "published_date": "18-05-2026",
        "scope": "Unaudited consolidated FY26 results; INR values.",
        "inputs": {
            "operating_cf": 82_824_000_000.0,
            "capex": 95_351_000_000.0,
            "interest_expense": 61_754_000_000.0,
            "pretax_income": 13_620_000_000.0,
            "tax_provision": 3_235_000_000.0,
        },
        "input_note": (
            "The FCFF financing input is ReNew's reported finance costs and fair-value "
            "change in derivative instruments, used as a disclosed finance-cost proxy."
        ),
    },
    "WAAREEENER.NS": {
        "source_name": "Waaree Energies FY26 audited results and investor presentation",
        "source_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "3b7347d1-3e49-4d4a-9899-fd58acaa0142.pdf"
        ),
        "source_type": "Official BSE filing",
        "statement_date": "31-03-2026",
        "published_date": "29-04-2026",
        "scope": "Audited consolidated FY26 results; INR values.",
        "inputs": {
            "operating_cf": 16_269_500_000.0,
            "capex": 48_817_700_000.0,
            "interest_expense": 2_805_000_000.0,
            "pretax_income": 50_517_900_000.0,
            "tax_provision": 11_676_400_000.0,
        },
        "input_note": (
            "Official results confirm FY26 OCF and finance/tax inputs; disclosed FY26 "
            "capital expenditure of approximately ₹4,881 crore aligns with the exact feed."
        ),
    },
    "PREMIERENE.NS": {
        "source_name": "Premier Energies FY26 audited financial results",
        "source_url": (
            "https://premierenergies.com/downloads/"
            "1778851148_Outcome%20of%20the%20Board%20Meeting%20(1).pdf"
        ),
        "source_type": "Official company filing",
        "statement_date": "31-03-2026",
        "published_date": "15-05-2026",
        "scope": "Audited consolidated FY26 results; INR values.",
        "inputs": {
            "operating_cf": 12_610_560_000.0,
            "capex": 29_977_420_000.0,
            "interest_expense": 1_581_780_000.0,
            "pretax_income": 19_732_060_000.0,
            "tax_provision": 4_635_170_000.0,
        },
        "input_note": "Finance costs are used as the disclosed financing-expense proxy.",
    },
    "VIKRAMSOLR.NS": {
        "source_name": "Vikram Solar FY26 audited financial results",
        "source_url": (
            "https://www.vikramsolar.com/wp-content/uploads/2026/05/"
            "VSL-Audited-Results-FY-26.pdf"
        ),
        "source_type": "Official company filing",
        "statement_date": "31-03-2026",
        "published_date": "07-05-2026",
        "scope": "Audited consolidated FY26 results; INR values.",
        "inputs": {
            "operating_cf": 6_295_480_000.0,
            "capex": 7_220_930_000.0,
            "interest_expense": 1_605_600_000.0,
            "pretax_income": 6_469_610_000.0,
            "tax_provision": 1_765_400_000.0,
        },
        "input_note": "Finance costs are used as the disclosed financing-expense proxy.",
    },
    "EMMVEE.NS": {
        "source_name": "Emmvee FY26 audited financial results",
        "source_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "bb96a3bb-7600-4cbc-bee1-edfaedc94dff.pdf"
        ),
        "source_type": "Official BSE filing",
        "statement_date": "31-03-2026",
        "published_date": "28-04-2026",
        "scope": "Audited consolidated FY26 results; INR values.",
        "inputs": {
            "operating_cf": 2_001_377_000.0,
            "capex": 6_530_524_000.0,
            "interest_expense": 1_546_619_000.0,
            "pretax_income": 13_375_953_000.0,
            "tax_provision": 2_560_438_000.0,
        },
        "input_note": "Finance costs are used as the disclosed financing-expense proxy.",
    },
}


def yahoo_financials_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/cash-flow/"


def _yahoo_source_urls(ticker: str) -> dict[str, str]:
    encoded = quote(ticker, safe="")
    base = f"https://finance.yahoo.com/quote/{encoded}"
    return {
        "market_source_url": f"{base}/key-statistics/",
        "income_statement_source_url": f"{base}/financials/",
        "balance_sheet_source_url": f"{base}/balance-sheet/",
        "cash_flow_market_source_url": f"{base}/cash-flow/",
    }


def _parse_date(value: str) -> date | None:
    for pattern in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _comparison_detail(
    market_inputs: dict[str, float | None],
    official_inputs: dict[str, float],
) -> str:
    labels = {
        "operating_cf": "OCF",
        "capex": "capex",
        "interest_expense": "interest/finance cost",
        "pretax_income": "pretax income",
        "tax_provision": "tax provision",
    }
    differences = []
    compared = 0
    for key, official_value in official_inputs.items():
        market_value = market_inputs.get(key)
        if market_value is None:
            continue
        compared += 1
        if abs(market_value - official_value) > 1:
            differences.append(
                f"{labels[key]} Yahoo ₹{market_value / 1e9:,.3f}bn vs "
                f"official ₹{official_value / 1e9:,.3f}bn"
            )
    if differences:
        return "Line-item differences retained in the audit: " + "; ".join(differences) + "."
    if compared:
        return "Yahoo values agree with the official source for the compared line items."
    return "Yahoo did not expose enough matching line items for a numeric comparison."


def cash_flow_source(
    ticker: str,
    market_statement_date: str,
    market_inputs: dict[str, float | None],
) -> tuple[dict[str, float | None], dict]:
    market_url = yahoo_financials_url(ticker)
    yahoo_urls = _yahoo_source_urls(ticker)
    source = OFFICIAL_CASH_FLOW_SOURCES.get(ticker)
    captured_at = datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")
    if source is None:
        return market_inputs, {
            "data_source_name": "Yahoo Finance annual cash-flow feed",
            "data_source_url": market_url,
            "data_source_type": "Market-data fallback",
            **yahoo_urls,
            "cash_flow_statement_date": market_statement_date,
            "source_captured_at": captured_at,
            "source_freshness_status": "Official cross-check not configured",
            "cross_check_status": "Not cross-checked",
            "cross_check_detail": (
                "Values are linked to Yahoo Finance; add an authoritative filing "
                "before treating the figures as verified."
            ),
            "source_input_note": "",
        }

    official_date = _parse_date(source["statement_date"])
    market_date = _parse_date(market_statement_date)
    if market_date is not None and official_date is not None and market_date > official_date:
        return market_inputs, {
            "data_source_name": "Yahoo Finance annual cash-flow feed",
            "data_source_url": market_url,
            "data_source_type": "Market data newer than stored official cross-check",
            **yahoo_urls,
            "official_source_name": source["source_name"],
            "official_source_url": source["source_url"],
            "official_source_type": source["source_type"],
            "cash_flow_statement_date": market_statement_date,
            "source_captured_at": captured_at,
            "source_freshness_status": "Newer market period requires official re-verification",
            "cross_check_status": "Pending",
            "cross_check_detail": (
                f"Market feed period {market_statement_date} is newer than the stored "
                f"official source period {source['statement_date']}."
            ),
            "source_input_note": source["input_note"],
        }

    freshness = "Current official period"
    if market_date is not None and official_date is not None and market_date < official_date:
        freshness = (
            f"Official {source['statement_date']} values replace stale "
            f"market-feed period {market_statement_date}"
        )
    official_inputs = {
        name: float(value) for name, value in source["inputs"].items()
    }
    comparison = _comparison_detail(market_inputs, official_inputs)
    return official_inputs, {
        "data_source_name": source["source_name"],
        "data_source_url": source["source_url"],
        "data_source_type": source["source_type"],
        **yahoo_urls,
        "official_source_name": source["source_name"],
        "official_source_url": source["source_url"],
        "official_source_type": source["source_type"],
        "cash_flow_statement_date": source["statement_date"],
        "source_published_date": source["published_date"],
        "source_captured_at": captured_at,
        "source_freshness_status": freshness,
        "cross_check_status": "Verified against official filing",
        "cross_check_detail": f"{source['scope']} {comparison}",
        "source_input_note": source["input_note"],
        "official_raw_capex": -float(source["inputs"]["capex"]),
    }
