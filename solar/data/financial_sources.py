"""Official financial-statement registry, INR normalization and link validation.

Every statement-derived figure in the report is sourced from this registry, which
records the *raw* values exactly as published (with their original currency and
scale) plus a normalized INR value. Market prices are handled separately in
``solar.data.prices`` and are never treated as statement inputs.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from urllib.parse import quote, urlparse

import httpx

from solar.config import IST


# Hosts we treat as authoritative for official financial statements. A citation
# is only ever labelled "official" when it lives on one of these domains.
APPROVED_OFFICIAL_HOSTS: frozenset[str] = frozenset({
    "www.sec.gov",
    "investor.renew.com",
    "www.waaree.com",
    "premierenergies.com",
    "www.premierenergies.com",
    "www.vikramsolar.com",
    "www.bseindia.com",
    "www.emmveepv.com",
    "www.nseindia.com",
})

# Fields that must come from an official statement (never from a market feed).
STATEMENT_FIELDS: tuple[str, ...] = (
    "revenue",
    "revenue_previous",
    "net_income",
    "net_income_previous",
    "pretax_income",
    "tax_provision",
    "finance_costs",
    "da",
    "total_assets",
    "current_assets",
    "current_liabilities",
    "inventory",
    "cash",
    "total_debt",
    "total_equity",
    "operating_cf",
    "capex",
)


OFFICIAL_FINANCIAL_STATEMENTS: dict[str, dict] = {
    "RNW": {
        "source_name": "ReNew Energy Global FY26 results (SEC Form 6-K, Exhibit 99.1)",
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1848763/"
            "000119312526227847/rnw-ex99_1.htm"
        ),
        "document_url": (
            "https://www.sec.gov/Archives/edgar/data/1848763/"
            "000119312526227847/rnw-ex99_1.htm"
        ),
        "landing_url": (
            "https://investor.renew.com/news-releases/news-release-details/"
            "renew-announces-results-fourth-quarter-and-full-fiscal-year"
        ),
        "source_type": "Official SEC filing (Form 6-K, Exhibit 99.1)",
        "statement_date": "31-03-2026",
        "published_date": "18-05-2026",
        "scope": "Unaudited consolidated FY26 results.",
        "raw_currency": "INR",
        "raw_unit": "INR million",
        "scale_to_inr": 1_000_000.0,
        "raw_values": {
            "revenue": 150_635.0,
            "revenue_previous": 109_070.0,
            "net_income": 10_385.0,
            "net_income_previous": 4_591.0,
            "pretax_income": 13_620.0,
            "tax_provision": 3_235.0,
            "finance_costs": 61_754.0,
            "da": None,
            "total_assets": 1_056_088.0,
            "current_assets": 135_283.0,
            "current_liabilities": 325_265.0,
            "inventory": 13_538.0,
            "cash": 22_845.0,
            "total_debt": 767_767.0,
            "total_equity": 144_396.0,
            "operating_cf": 82_824.0,
            "capex": 95_351.0,
        },
        "source_note": (
            "Finance costs (including fair-value change in derivative instruments) are "
            "used as the disclosed financing-expense proxy for FCFF."
        ),
    },
    "WAAREEENER.NS": {
        "source_name": "Waaree Energies FY26 audited results (company press release)",
        "source_url": (
            "https://www.waaree.com/upload/media/press_release_april_29_1777531272.pdf"
        ),
        "document_url": (
            "https://www.waaree.com/upload/media/"
            "investor_presentation_signed_1777531429.pdf"
        ),
        "landing_url": (
            "https://www.bseindia.com/stock-share-price/waaree-energies-ltd/"
            "waareeener/544277/corp-announcements/"
        ),
        "source_type": "Official company filing",
        "statement_date": "31-03-2026",
        "published_date": "29-04-2026",
        "scope": "Audited consolidated FY26 results.",
        "raw_currency": "INR",
        "raw_unit": "INR crore",
        "scale_to_inr": 10_000_000.0,
        "raw_values": {
            "revenue": 26_536.77,
            "revenue_previous": 14_444.50,
            "net_income": 3_884.15,
            "net_income_previous": 1_928.13,
            "pretax_income": 5_051.79,
            "tax_provision": 1_167.64,
            "finance_costs": 280.50,
            "da": 989.72,
            "total_assets": 30_115.37,
            "current_assets": None,
            "current_liabilities": 12_707.70,
            "inventory": 5_855.64,
            "cash": 774.16,
            "total_debt": 5_491.53,
            "total_equity": 15_010.89,
            "operating_cf": 1_626.95,
            "capex": 4_381.77,
        },
        "source_note": (
            "FY26 capex is the audited cash-flow figure of Rs 4,381.77 crore. Total "
            "current assets are withheld pending a direct re-read of the audited "
            "balance sheet, so current/quick ratios show as unavailable rather than "
            "an unverified value."
        ),
    },
    "PREMIERENE.NS": {
        "source_name": "Premier Energies FY26 audited financial results",
        "source_url": (
            "https://premierenergies.com/downloads/"
            "1778851148_Outcome%20of%20the%20Board%20Meeting%20(1).pdf"
        ),
        "document_url": (
            "https://premierenergies.com/downloads/"
            "1778851220_Investor%20Presentation%20Q4%20FY%202026%20.pdf"
        ),
        "landing_url": "https://premierenergies.com/investors",
        "source_type": "Official company filing",
        "statement_date": "31-03-2026",
        "published_date": "15-05-2026",
        "scope": "Audited consolidated FY26 results.",
        "raw_currency": "INR",
        "raw_unit": "INR million",
        "scale_to_inr": 1_000_000.0,
        "raw_values": {
            "revenue": 78_243.74,
            "revenue_previous": 65_187.45,
            "net_income": 15_096.89,
            "net_income_previous": 9_371.32,
            "pretax_income": 19_732.06,
            "tax_provision": 4_635.17,
            "finance_costs": 1_581.78,
            "da": None,
            "total_assets": 108_448.63,
            "current_assets": 58_691.18,
            "current_liabilities": 32_013.54,
            "inventory": 20_373.50,
            "cash": 14_665.22,
            "total_debt": 27_168.07,
            "total_equity": 43_103.62,
            "operating_cf": 12_610.56,
            "capex": 29_977.42,
        },
        "source_note": "Finance costs are used as the disclosed financing-expense proxy.",
    },
    "VIKRAMSOLR.NS": {
        "source_name": "Vikram Solar FY26 audited financial results",
        "source_url": (
            "https://www.vikramsolar.com/wp-content/uploads/2026/05/"
            "VSL-Audited-Results-FY-26.pdf"
        ),
        "document_url": (
            "https://www.vikramsolar.com/wp-content/uploads/2026/05/"
            "VSL-Audited-Results-FY-26.pdf"
        ),
        "landing_url": "https://www.vikramsolar.com/investor-relations/",
        "source_type": "Official company filing",
        "statement_date": "31-03-2026",
        "published_date": "07-05-2026",
        "scope": "Audited consolidated FY26 results.",
        "raw_currency": "INR",
        "raw_unit": "INR million",
        "scale_to_inr": 1_000_000.0,
        "raw_values": {
            "revenue": 48_022.51,
            "revenue_previous": 34_234.53,
            "net_income": 4_704.24,
            "net_income_previous": None,
            "pretax_income": 6_469.61,
            "tax_provision": 1_765.40,
            "finance_costs": 1_605.60,
            "da": 1_620.10,
            "total_assets": 57_284.79,
            "current_assets": 37_271.34,
            "current_liabilities": 19_775.45,
            "inventory": 8_231.34,
            "cash": 357.73,
            "total_debt": 1_000.73,
            "total_equity": 31_677.60,
            "operating_cf": 6_295.48,
            "capex": 7_220.93,
        },
        "source_note": (
            "Finance costs are the disclosed financing-expense proxy. Prior-year net "
            "income is not stated on the same basis in the FY26 filing, so profit "
            "growth is shown as unavailable."
        ),
    },
    "EMMVEE.NS": {
        "source_name": "Emmvee Photovoltaic Power FY26 audited financial results",
        "source_url": "https://www.emmveepv.com/investors",
        "document_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "bb96a3bb-7600-4cbc-bee1-edfaedc94dff.pdf"
        ),
        "landing_url": (
            "https://www.bseindia.com/stock-share-price/"
            "emmvee-photovoltaic-power-ltd/emmvee/544608/corp-announcements/"
        ),
        "source_type": "Official company investor-relations page",
        "statement_date": "31-03-2026",
        "published_date": "28-04-2026",
        "scope": "Audited consolidated FY26 results.",
        "raw_currency": "INR",
        "raw_unit": "INR lakh",
        "scale_to_inr": 100_000.0,
        "raw_values": {
            "revenue": 504_917.73,
            "revenue_previous": 233_561.34,
            "net_income": 108_155.15,
            "net_income_previous": 36_901.44,
            "pretax_income": 133_759.53,
            "tax_provision": 25_604.38,
            "finance_costs": 15_466.19,
            "da": 29_563.27,
            "total_assets": 577_249.20,
            "current_assets": 305_968.25,
            "current_liabilities": 148_467.50,
            "inventory": 171_055.42,
            "cash": 24_262.32,
            "total_debt": 17_726.40,
            "total_equity": 369_494.09,
            "operating_cf": 20_013.77,
            "capex": 65_305.24,
        },
        "source_note": (
            "Values are published in INR lakh and normalized to rupees. The company "
            "investor-relations page is the stable primary citation; the BSE announcement "
            "page and exact attachment PDF are offered as secondary links."
        ),
    },
}

# Backwards-compatible alias: the cash-flow registry is now a view over the full
# statement registry.
OFFICIAL_CASH_FLOW_SOURCES = OFFICIAL_FINANCIAL_STATEMENTS


def normalized_values(statement: dict) -> dict[str, float | None]:
    """Return every raw statement value multiplied into rupees."""
    scale = statement["scale_to_inr"]
    values: dict[str, float | None] = {}
    for field in STATEMENT_FIELDS:
        raw = statement["raw_values"].get(field)
        values[field] = None if raw is None else round(float(raw) * scale, 2)
    return values


def official_statement(ticker: str) -> dict | None:
    """Return the normalized official statement for ``ticker`` or ``None``.

    The returned dict exposes both the raw published values (with their original
    currency/unit) and the INR-normalized values, plus all source metadata.
    """
    statement = OFFICIAL_FINANCIAL_STATEMENTS.get(ticker)
    if statement is None:
        return None
    return {
        "source_name": statement["source_name"],
        "source_url": statement["source_url"],
        "document_url": statement.get("document_url"),
        "landing_url": statement.get("landing_url"),
        "source_type": statement["source_type"],
        "statement_date": statement["statement_date"],
        "published_date": statement["published_date"],
        "scope": statement["scope"],
        "currency": "INR",
        "raw_currency": statement["raw_currency"],
        "raw_unit": statement["raw_unit"],
        "scale_to_inr": statement["scale_to_inr"],
        "raw_values": dict(statement["raw_values"]),
        "values": normalized_values(statement),
        "source_note": statement.get("source_note", ""),
    }


def is_approved_official_host(url: str) -> bool:
    """True when ``url`` is HTTPS and hosted on an approved official domain."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.lower() in APPROVED_OFFICIAL_HOSTS


def classify_source_response(
    url: str,
    status_code: int | None,
    content_type: str,
    sample: bytes,
    checked_at: str,
) -> dict:
    """Classify a source URL response without performing any network I/O.

    Returns a dict with ``status`` (``valid`` / ``blocked`` / ``invalid``) plus a
    human-readable ``reason`` and the ``checked_at`` timestamp.
    """
    result = {"url": url, "status": "invalid", "reason": "", "checked_at": checked_at}
    if not is_approved_official_host(url):
        result["reason"] = "URL is not an approved HTTPS official source"
        return result
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = (
            f"Automated validation blocked (HTTP {status_code}); official source is "
            "kept and should be opened in a browser"
        )
        return result
    if status_code is None or status_code >= 400:
        result["reason"] = f"Source returned HTTP {status_code}"
        return result
    lowered_type = (content_type or "").lower()
    expects_pdf = url.lower().endswith(".pdf")
    looks_like_pdf = sample[:5] == b"%PDF-"
    looks_like_html = b"<html" in sample[:2048].lower() or "html" in lowered_type
    if expects_pdf:
        if looks_like_html:
            result["reason"] = (
                "Expected a PDF but received an HTML page (likely a block/error page)"
            )
            return result
        if looks_like_pdf or "application/pdf" in lowered_type:
            result["status"] = "valid"
            result["reason"] = "Validated PDF document"
            return result
        result["reason"] = "Expected a PDF but content type could not be confirmed"
        return result
    result["status"] = "valid"
    result["reason"] = "Validated official page"
    return result


@lru_cache(maxsize=32)
def validate_source_url(url: str, timeout: float = 15.0) -> dict:
    """Fetch ``url`` and classify it. Network errors are reported, not raised."""
    checked_at = datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")
    if not is_approved_official_host(url):
        return {
            "url": url,
            "status": "invalid",
            "reason": "URL is not an approved HTTPS official source",
            "checked_at": checked_at,
        }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SolarReport/1.0; +https://www.sec.gov) "
            "financial-report-validator"
        )
    }
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers=headers
        ) as client:
            response = client.get(url)
            return classify_source_response(
                url,
                response.status_code,
                response.headers.get("content-type", ""),
                response.content[:2048],
                checked_at,
            )
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "status": "blocked",
            "reason": f"Automated validation could not reach the source: {exc}",
            "checked_at": checked_at,
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
        if market_value is None or official_value is None:
            continue
        compared += 1
        if abs(market_value - official_value) > 1:
            differences.append(
                f"{labels[key]} Yahoo Rs {market_value / 1e9:,.3f}bn vs "
                f"official Rs {official_value / 1e9:,.3f}bn"
            )
    if differences:
        return (
            "Non-authoritative market comparison (not used in the calculation): "
            + "; ".join(differences)
            + "."
        )
    if compared:
        return (
            "Non-authoritative market comparison agrees with the official source for "
            "the compared line items."
        )
    return "No market line items were available for a non-authoritative comparison."


def cash_flow_source(
    ticker: str,
    market_statement_date: str,
    market_inputs: dict[str, float | None],
) -> tuple[dict[str, float | None], dict]:
    """Return official cash-flow inputs plus source metadata.

    Official statement values are always used when a registry entry exists; the
    market feed is only retained as a non-authoritative comparison and is never
    substituted for a missing official value.
    """
    market_url = yahoo_financials_url(ticker)
    yahoo_urls = _yahoo_source_urls(ticker)
    source = OFFICIAL_FINANCIAL_STATEMENTS.get(ticker)
    captured_at = datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")
    if source is None:
        return market_inputs, {
            "data_source_name": "Yahoo Finance annual cash-flow feed",
            "data_source_url": market_url,
            "data_source_type": "Market-data (no official statement configured)",
            **yahoo_urls,
            "cash_flow_statement_date": market_statement_date,
            "source_captured_at": captured_at,
            "source_freshness_status": "Official statement unavailable",
            "source_link_status": "unavailable",
            "cross_check_status": "Official statement unavailable",
            "cross_check_detail": (
                "No official filing is configured for this company, so cash-flow "
                "figures cannot be shown as statement-verified."
            ),
            "source_input_note": "",
        }

    official_date = _parse_date(source["statement_date"])
    market_date = _parse_date(market_statement_date)
    freshness = "Current official period"
    if market_date is not None and official_date is not None and market_date < official_date:
        freshness = (
            f"Official {source['statement_date']} values replace stale "
            f"market-feed period {market_statement_date}"
        )
    normalized = normalized_values(source)
    official_inputs = {
        "operating_cf": normalized["operating_cf"],
        "capex": normalized["capex"],
        "interest_expense": normalized["finance_costs"],
        "pretax_income": normalized["pretax_income"],
        "tax_provision": normalized["tax_provision"],
    }
    comparison = _comparison_detail(market_inputs, official_inputs)
    capex = official_inputs["capex"]
    return official_inputs, {
        "data_source_name": source["source_name"],
        "data_source_url": source["source_url"],
        "data_source_type": source["source_type"],
        "document_url": source.get("document_url"),
        "landing_url": source.get("landing_url"),
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
        "source_input_note": source.get("source_note", ""),
        "official_raw_capex": None if capex is None else -float(capex),
    }
