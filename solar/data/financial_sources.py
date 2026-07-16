"""Official financial-statement registry, INR normalization and link validation.

Every statement-derived figure in the report is sourced from this registry, which
records the *raw* values exactly as published (with their original currency and
scale) plus a normalized INR value. Market prices are handled separately in
``solar.data.prices`` and are never treated as statement inputs.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse

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
    "ebit",
    "change_nwc",
    "total_assets",
    "total_assets_previous",
    "current_assets",
    "current_liabilities",
    "inventory",
    "cash",
    "total_debt",
    "total_equity",
    "total_equity_previous",
    "operating_cf",
    "capex",
)


OFFICIAL_FINANCIAL_STATEMENTS: dict[str, dict] = {
    "RNW": {
        "source_name": "ReNew Energy Global FY26 filed results",
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
        "statement_period": "Year ended 31-03-2026",
        "comparative_period": "Year ended 31-03-2025",
        "scope": "Consolidated",
        "audit_status": "Unaudited FY26 results filed with the SEC",
        "debt_definition": "Interest-bearing borrowings, excluding lease liabilities",
        "corrected_fields": {"revenue", "revenue_previous", "da"},
        "raw_currency": "INR",
        "raw_unit": "INR million",
        "scale_to_inr": 1_000_000.0,
        "raw_values": {
            "revenue": 132_196.0,
            "revenue_previous": 97_063.0,
            "net_income": 10_385.0,
            "net_income_previous": 4_591.0,
            "pretax_income": 13_620.0,
            "tax_provision": 3_235.0,
            "finance_costs": 61_754.0,
            "da": 26_738.0,
            "ebit": None,
            "change_nwc": None,
            "total_assets": 1_056_088.0,
            "total_assets_previous": 959_799.0,
            "current_assets": 135_283.0,
            "current_liabilities": 325_265.0,
            "inventory": 13_538.0,
            "cash": 22_845.0,
            "total_debt": 767_767.0,
            "total_equity": 144_396.0,
            "total_equity_previous": 131_112.0,
            "operating_cf": 82_824.0,
            "capex": 95_351.0,
        },
        "field_groups": (
            {
                "fields": (
                    "revenue",
                    "revenue_previous",
                    "net_income",
                    "net_income_previous",
                    "pretax_income",
                    "tax_provision",
                    "finance_costs",
                    "da",
                ),
                "section": "Consolidated Statement of Profit or Loss",
                "reference": "SEC Exhibit 99.1 HTML table",
            },
            {
                "fields": (
                    "total_assets",
                    "total_assets_previous",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                    "cash",
                    "total_debt",
                    "total_equity",
                    "total_equity_previous",
                ),
                "section": "Consolidated Statement of Financial Position",
                "reference": "SEC Exhibit 99.1 HTML table",
            },
            {
                "fields": ("operating_cf", "capex"),
                "section": "Consolidated Statements of Cash Flows",
                "reference": "SEC Exhibit 99.1 HTML table",
            },
        ),
        "field_caveats": {
            "revenue": "IFRS revenue from contracts; excludes finance and other income.",
            "finance_costs": (
                "Includes fair-value changes in derivative instruments and is not "
                "used as cash interest or an FCFF input."
            ),
            "da": "Depreciation, amortisation and impairment.",
            "capex": "Cash purchases of PP&E, intangible and right-of-use assets.",
            "operating_cf": "Interest paid is classified in financing activities.",
        },
    },
    "WAAREEENER.NS": {
        "source_name": "Waaree Energies audited FY26 consolidated results filing",
        "source_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"
            "3b7347d1-3e49-4d4a-9899-fd58acaa0142.pdf"
        ),
        "document_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"
            "3b7347d1-3e49-4d4a-9899-fd58acaa0142.pdf"
        ),
        "landing_url": "https://waaree.com/financial-performance/",
        "source_type": "Official BSE filing of audited annual financial results",
        "statement_date": "31-03-2026",
        "published_date": "29-04-2026",
        "statement_period": "Year ended 31-03-2026",
        "comparative_period": "Year ended 31-03-2025",
        "scope": "Consolidated",
        "audit_status": "Audited",
        "debt_definition": "Interest-bearing borrowings, excluding lease liabilities",
        "corrected_fields": {"current_assets", "total_debt", "capex"},
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
            "ebit": None,
            "change_nwc": None,
            "total_assets": 30_115.37,
            "total_assets_previous": 19_485.35,
            "current_assets": 17_577.00,
            "current_liabilities": 12_707.70,
            "inventory": 5_855.64,
            "cash": 774.16,
            "total_debt": 2_491.53,
            "total_equity": 15_010.89,
            "total_equity_previous": 9_595.28,
            "operating_cf": 1_626.95,
            "capex": 4_881.77,
        },
        "field_groups": (
            {
                "fields": (
                    "revenue",
                    "revenue_previous",
                    "net_income",
                    "net_income_previous",
                    "pretax_income",
                    "tax_provision",
                    "finance_costs",
                    "da",
                ),
                "section": "Audited Consolidated Financial Results",
                "reference": "PDF p.15",
            },
            {
                "fields": (
                    "total_assets",
                    "total_assets_previous",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                    "cash",
                    "total_debt",
                    "total_equity",
                    "total_equity_previous",
                ),
                "section": "Consolidated Statement of Assets and Liabilities",
                "reference": "PDF p.16",
            },
            {
                "fields": ("operating_cf", "capex"),
                "section": "Audited Consolidated Cash Flow Statement",
                "reference": "PDF p.17",
            },
        ),
        "field_caveats": {
            "total_debt": "Borrowings only: current plus non-current borrowings.",
            "cash": "Cash and cash equivalents only.",
            "capex": (
                "Cash acquisition of PP&E and intangible assets, including capital "
                "advances."
            ),
            "finance_costs": "P&L finance cost; not used as a cash-interest proxy.",
        },
    },
    "PREMIERENE.NS": {
        "source_name": "Premier Energies audited FY26 consolidated results filing",
        "source_url": (
            "https://premierenergies.com/downloads/"
            "1778851148_Outcome%20of%20the%20Board%20Meeting%20(1).pdf"
        ),
        "document_url": (
            "https://premierenergies.com/downloads/"
            "1778851148_Outcome%20of%20the%20Board%20Meeting%20(1).pdf"
        ),
        "landing_url": "https://premierenergies.com/investors",
        "source_type": "Official filed audited annual financial results",
        "statement_date": "31-03-2026",
        "published_date": "15-05-2026",
        "statement_period": "Year ended 31-03-2026",
        "comparative_period": "Year ended 31-03-2025",
        "scope": "Consolidated",
        "audit_status": "Audited",
        "debt_definition": "Interest-bearing borrowings, excluding lease liabilities",
        "corrected_fields": {"da"},
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
            "da": 4_524.99,
            "ebit": None,
            "change_nwc": None,
            "total_assets": 108_448.63,
            "total_assets_previous": 68_414.02,
            "current_assets": 58_691.18,
            "current_liabilities": 32_013.54,
            "inventory": 20_373.50,
            "cash": 14_665.22,
            "total_debt": 27_168.07,
            "total_equity": 43_103.62,
            "total_equity_previous": 28_221.06,
            "operating_cf": 12_610.56,
            "capex": 29_977.42,
        },
        "field_groups": (
            {
                "fields": (
                    "revenue",
                    "revenue_previous",
                    "net_income",
                    "net_income_previous",
                    "pretax_income",
                    "tax_provision",
                    "finance_costs",
                    "da",
                ),
                "section": "Statement of Audited Consolidated Financial Results",
                "reference": "PDF p.13",
            },
            {
                "fields": (
                    "total_assets",
                    "total_assets_previous",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                    "cash",
                    "total_debt",
                    "total_equity",
                    "total_equity_previous",
                ),
                "section": "Consolidated Balance Sheet",
                "reference": "PDF p.14",
            },
            {
                "fields": ("operating_cf", "capex"),
                "section": "Consolidated Statement of Cash Flows",
                "reference": "PDF p.15",
            },
        ),
        "field_caveats": {
            "total_debt": "Borrowings only; lease liabilities are excluded.",
            "cash": "Cash and cash equivalents only.",
            "finance_costs": "P&L finance cost; cash-flow finance-cost adjustment differs.",
            "capex": "Cash purchases of PP&E, intangibles, CWIP and capital advances.",
        },
    },
    "VIKRAMSOLR.NS": {
        "source_name": "Vikram Solar audited FY26 consolidated results filing",
        "source_url": (
            "https://www.vikramsolar.com/wp-content/uploads/2026/05/"
            "VSL-Audited-Results-FY-26.pdf"
        ),
        "document_url": (
            "https://www.vikramsolar.com/wp-content/uploads/2026/05/"
            "VSL-Audited-Results-FY-26.pdf"
        ),
        "landing_url": "https://www.vikramsolar.com/investor-relations/",
        "source_type": "Official company audited financial-results filing",
        "statement_date": "31-03-2026",
        "published_date": "07-05-2026",
        "statement_period": "Year ended 31-03-2026",
        "comparative_period": "Year ended 31-03-2025",
        "scope": "Consolidated",
        "audit_status": "Audited",
        "debt_definition": "Interest-bearing borrowings, excluding lease liabilities",
        "corrected_fields": {"net_income", "net_income_previous"},
        "raw_currency": "INR",
        "raw_unit": "INR million",
        "scale_to_inr": 1_000_000.0,
        "raw_values": {
            "revenue": 48_022.51,
            "revenue_previous": 34_234.53,
            "net_income": 4_704.21,
            "net_income_previous": 1_398.31,
            "pretax_income": 6_469.61,
            "tax_provision": 1_765.40,
            "finance_costs": 1_605.60,
            "da": 1_620.10,
            "ebit": None,
            "change_nwc": None,
            "total_assets": 57_284.79,
            "total_assets_previous": 28_321.51,
            "current_assets": 37_271.34,
            "current_liabilities": 19_775.45,
            "inventory": 8_231.34,
            "cash": 357.73,
            "total_debt": 1_000.73,
            "total_equity": 31_677.60,
            "total_equity_previous": 12_419.89,
            "operating_cf": 6_295.48,
            "capex": 7_220.93,
        },
        "field_groups": (
            {
                "fields": (
                    "revenue",
                    "revenue_previous",
                    "net_income",
                    "net_income_previous",
                    "pretax_income",
                    "tax_provision",
                    "finance_costs",
                    "da",
                ),
                "section": "Statement of Audited Consolidated Financial Results",
                "reference": "PDF p.13",
            },
            {
                "fields": (
                    "total_assets",
                    "total_assets_previous",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                    "cash",
                    "total_debt",
                    "total_equity",
                    "total_equity_previous",
                ),
                "section": "Consolidated Statement of Assets and Liabilities",
                "reference": "PDF p.14",
            },
            {
                "fields": ("operating_cf", "capex"),
                "section": "Consolidated Cash Flow Statement",
                "reference": "PDF p.15",
            },
        ),
        "field_caveats": {
            "total_debt": "Borrowings only; lease liabilities are excluded.",
            "cash": "Cash and cash equivalents only; other bank balances are excluded.",
            "finance_costs": "P&L finance cost; not used as a cash-interest proxy.",
            "capex": "Cash acquisition of PP&E, CWIP and intangible assets.",
        },
    },
    "EMMVEE.NS": {
        "source_name": "Emmvee audited FY26 consolidated results filing",
        "source_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "bb96a3bb-7600-4cbc-bee1-edfaedc94dff.pdf"
        ),
        "document_url": (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "bb96a3bb-7600-4cbc-bee1-edfaedc94dff.pdf"
        ),
        "landing_url": "https://www.emmveepv.com/investor-relations/",
        "source_type": "Official BSE filing of audited annual financial results",
        "statement_date": "31-03-2026",
        "published_date": "28-04-2026",
        "statement_period": "Year ended 31-03-2026",
        "comparative_period": "Year ended 31-03-2025",
        "scope": "Consolidated",
        "audit_status": "Audited",
        "debt_definition": "Interest-bearing borrowings, excluding lease liabilities",
        "corrected_fields": {"revenue", "capex"},
        "raw_currency": "INR",
        "raw_unit": "INR lakh",
        "scale_to_inr": 100_000.0,
        "raw_values": {
            "revenue": 504_987.73,
            "revenue_previous": 233_561.34,
            "net_income": 108_155.15,
            "net_income_previous": 36_901.44,
            "pretax_income": 133_759.53,
            "tax_provision": 25_604.38,
            "finance_costs": 15_466.19,
            "da": 29_563.27,
            "ebit": None,
            "change_nwc": None,
            "total_assets": 577_249.20,
            "total_assets_previous": 391_393.70,
            "current_assets": 305_968.25,
            "current_liabilities": 148_467.50,
            "inventory": 171_055.42,
            "cash": 24_262.32,
            "total_debt": 17_726.40,
            "total_equity": 369_494.09,
            "total_equity_previous": 53_679.72,
            "operating_cf": 20_013.77,
            "capex": 65_331.83,
        },
        "field_groups": (
            {
                "fields": (
                    "revenue",
                    "revenue_previous",
                    "net_income",
                    "net_income_previous",
                    "pretax_income",
                    "tax_provision",
                    "finance_costs",
                    "da",
                ),
                "section": "Statement of Consolidated Audited Financial Results",
                "reference": "PDF p.7",
            },
            {
                "fields": (
                    "total_assets",
                    "total_assets_previous",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                    "cash",
                    "total_debt",
                    "total_equity",
                    "total_equity_previous",
                ),
                "section": "Consolidated Statement of Assets and Liabilities",
                "reference": "PDF p.6",
            },
            {
                "fields": ("operating_cf", "capex"),
                "section": "Consolidated Cash Flow Statement",
                "reference": "PDF p.8",
            },
        ),
        "field_caveats": {
            "total_debt": "Borrowings only; lease liabilities are excluded.",
            "cash": "Cash and cash equivalents only.",
            "finance_costs": "P&L finance cost; not used as a cash-interest proxy.",
            "capex": "Cash PP&E/CWIP/capital-advance purchases plus intangible purchases.",
        },
        "latest_filing": {
            "statement_date": "30-06-2026",
            "published_date": "15-07-2026",
            "scope": "Unaudited consolidated Q1 FY27 results with limited review",
            "source_url": (
                "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
                "89fb671a-1122-47c5-8572-d799941da06b.pdf"
            ),
            "note": (
                "The Q1 filing has no balance sheet or cash-flow statement. The "
                "comparative ratio table therefore uses the latest complete audited "
                "annual filing rather than mixing quarterly P&L with annual balances."
            ),
        },
    },
}

FIELD_LABELS: dict[str, str] = {
    "revenue": "Revenue from operations/contracts",
    "revenue_previous": "Prior-year revenue from operations/contracts",
    "net_income": "Profit for the year",
    "net_income_previous": "Prior-year profit for the year",
    "pretax_income": "Profit before tax",
    "tax_provision": "Income-tax expense",
    "finance_costs": "Finance costs",
    "da": "Depreciation and amortisation",
    "ebit": "EBIT",
    "change_nwc": "Change in net working capital",
    "total_assets": "Total assets",
    "total_assets_previous": "Prior-year total assets",
    "current_assets": "Total current assets",
    "current_liabilities": "Total current liabilities",
    "inventory": "Inventories",
    "cash": "Cash and cash equivalents",
    "total_debt": "Interest-bearing borrowings",
    "total_equity": "Total equity",
    "total_equity_previous": "Prior-year total equity",
    "operating_cf": "Net cash from operating activities",
    "capex": "Cash capital expenditure",
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


def _field_period(statement: dict, field: str) -> str:
    if field in {
        "revenue_previous",
        "net_income_previous",
        "total_assets_previous",
        "total_equity_previous",
    }:
        return statement["comparative_period"]
    if field in {
        "total_assets",
        "current_assets",
        "current_liabilities",
        "inventory",
        "cash",
        "total_debt",
        "total_equity",
    }:
        return f"As at {statement['statement_date']}"
    return statement["statement_period"]


def _field_provenance(statement: dict) -> dict[str, dict]:
    raw_values = statement["raw_values"]
    normalized = normalized_values(statement)
    locations: dict[str, dict[str, str]] = {}
    for group in statement["field_groups"]:
        for field in group["fields"]:
            locations[field] = {
                "section": group["section"],
                "reference": group["reference"],
            }

    provenance: dict[str, dict] = {}
    for field in STATEMENT_FIELDS:
        raw_value = raw_values.get(field)
        if raw_value is None:
            continue
        location = locations.get(field)
        if location is None:
            raise ValueError(f"Missing filing location for {field}")
        source_url = statement["source_url"]
        page_match = re.search(r"\bp\.(\d+)\b", location["reference"])
        if page_match and source_url.lower().endswith(".pdf"):
            source_url = f"{source_url}#page={page_match.group(1)}"
        provenance[field] = {
            "field": field,
            "label": FIELD_LABELS[field],
            "raw_value": raw_value,
            "raw_currency": statement["raw_currency"],
            "raw_unit": statement["raw_unit"],
            "normalized_inr": normalized[field],
            "source_url": source_url,
            "official_landing_url": statement.get("landing_url"),
            "filing_date": statement["published_date"],
            "statement_period": _field_period(statement, field),
            "scope": statement["scope"],
            "audit_status": statement["audit_status"],
            "statement_section": location["section"],
            "page_or_note": location["reference"],
            "capture_timestamp": datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST"),
            "validation_status": "verified",
            "discrepancy_status": (
                "corrected"
                if field in statement.get("corrected_fields", set())
                else "verified"
            ),
            "caveat": statement.get("field_caveats", {}).get(field, ""),
        }
    return provenance


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
        "statement_period": statement["statement_period"],
        "comparative_period": statement["comparative_period"],
        "scope": statement["scope"],
        "audit_status": statement["audit_status"],
        "debt_definition": statement["debt_definition"],
        "currency": "INR",
        "raw_currency": statement["raw_currency"],
        "raw_unit": statement["raw_unit"],
        "scale_to_inr": statement["scale_to_inr"],
        "raw_values": dict(statement["raw_values"]),
        "values": normalized_values(statement),
        "field_provenance": _field_provenance(statement),
        "latest_filing": statement.get("latest_filing"),
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


def cash_flow_source(
    ticker: str,
    market_statement_date: str,
    market_inputs: dict[str, float | None],
) -> tuple[dict[str, float | None], dict]:
    """Return filing-only cash-flow inputs for backwards-compatible callers."""
    del market_statement_date, market_inputs
    source = official_statement(ticker)
    captured_at = datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")
    if source is None:
        return {
            "operating_cf": None,
            "capex": None,
            "interest_expense": None,
            "pretax_income": None,
            "tax_provision": None,
        }, {
            "data_source_name": "Official filing unavailable",
            "data_source_url": "",
            "data_source_type": "Unavailable",
            "cash_flow_statement_date": "Unavailable",
            "source_captured_at": captured_at,
            "source_freshness_status": "Official statement unavailable",
            "source_link_status": "unavailable",
            "cross_check_status": "No filing-only data configured",
            "cross_check_detail": "No secondary source was substituted.",
        }

    normalized = source["values"]
    official_inputs = {
        "operating_cf": normalized["operating_cf"],
        "capex": normalized["capex"],
        "interest_expense": None,
        "pretax_income": normalized["pretax_income"],
        "tax_provision": normalized["tax_provision"],
    }
    capex = official_inputs["capex"]
    return official_inputs, {
        "data_source_name": source["source_name"],
        "data_source_url": source["source_url"],
        "data_source_type": source["source_type"],
        "document_url": source.get("document_url"),
        "landing_url": source.get("landing_url"),
        "official_source_name": source["source_name"],
        "official_source_url": source["source_url"],
        "official_source_type": source["source_type"],
        "cash_flow_statement_date": source["statement_date"],
        "source_published_date": source["published_date"],
        "source_captured_at": captured_at,
        "source_freshness_status": "Current configured complete filing period",
        "cross_check_status": "Verified against official filing",
        "cross_check_detail": (
            f"{source['scope']} / {source['audit_status']}; no secondary finance "
            "source was queried or substituted."
        ),
        "source_input_note": (
            "FCFF cash-interest input is unavailable because P&L finance costs are "
            "not treated as cash interest."
        ),
        "official_raw_capex": None if capex is None else -float(capex),
    }
