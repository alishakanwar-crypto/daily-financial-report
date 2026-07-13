"""Configuration for the Solar Industry Report system."""

from __future__ import annotations

from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings

# Canonical Indian Standard Time (UTC+5:30, no DST) — all operations use IST.
IST = ZoneInfo("Asia/Kolkata")


class Company:
    """A tracked solar company."""

    def __init__(
        self,
        name: str,
        ticker: Optional[str],
        currency: str,
        exchange: str,
        listed: bool,
        website: str = "",
        note: str = "",
        active: bool = True,
        listing_status: str = "",
        consecutive_failures: int = 0,
    ):
        self.name = name
        self.ticker = ticker
        self.currency = currency
        self.exchange = exchange
        self.listed = listed
        self.website = website
        self.note = note
        self.active = active
        self.listing_status = listing_status or ("listed" if listed else "private")
        self.consecutive_failures = consecutive_failures


# --- The competitive set: Indian solar technology companies ---
DEFAULT_COMPANIES: List[Company] = [
    Company(
        "ReNew Energy Global",
        "RNW",
        "USD",
        "NASDAQ",
        listed=True,
        website="https://www.renew.com",
        note="ReNew Power — India's largest renewable IPP, listed on NASDAQ (USD).",
    ),
    Company(
        "Waaree Energies",
        "WAAREEENER.NS",
        "INR",
        "NSE",
        listed=True,
        website="https://www.waaree.com",
        note="India's largest solar PV module manufacturer.",
    ),
    Company(
        "Premier Energies",
        "PREMIERENE.NS",
        "INR",
        "NSE",
        listed=True,
        website="https://www.premierenergies.com",
        note="Integrated solar cell & module manufacturer.",
    ),
    Company(
        "Vikram Solar",
        "VIKRAMSOLR.NS",
        "INR",
        "NSE",
        listed=True,
        website="https://www.vikramsolar.com",
        note="Solar module manufacturer & EPC, listed 2025.",
    ),
    Company(
        "Emmvee Solar",
        "EMMVEE.NS",
        "INR",
        "NSE",
        listed=True,
        website="https://www.emmveepv.com",
        note="Emmvee Photovoltaic Power; NSE: EMMVEE, BSE: 544608, listed November 2025.",
    ),
]
COMPANIES = DEFAULT_COMPANIES


def listed_companies(companies: Optional[List[Company]] = None) -> List[Company]:
    source = companies if companies is not None else DEFAULT_COMPANIES
    return [c for c in source if c.active and c.listed and c.ticker]


SUPPLEMENTARY_TOPIC_CATALOG: list[dict[str, str]] = [
    {"name": "Iran crisis", "query": "Iran crisis latest developments"},
    {"name": "Middle East", "query": "Middle East geopolitics energy markets"},
    {"name": "Red Sea shipping", "query": "Red Sea shipping disruption freight rates"},
    {"name": "Russia–Ukraine", "query": "Russia Ukraine war energy commodities"},
    {"name": "China trade policy", "query": "China trade policy solar manufacturing exports"},
    {"name": "US tariffs", "query": "US tariffs solar imports clean energy"},
    {"name": "India–China relations", "query": "India China trade relations manufacturing"},
    {"name": "Energy security", "query": "global energy security supply disruption"},
    {"name": "Crude oil & LNG", "query": "crude oil LNG prices global energy markets"},
    {"name": "Global interest rates", "query": "global interest rates infrastructure financing"},
    {"name": "Rupee & currencies", "query": "Indian rupee dollar currency markets imports"},
    {"name": "Shipping & logistics", "query": "global shipping logistics freight supply chain"},
    {"name": "Critical minerals", "query": "critical minerals supply chain India clean energy"},
    {"name": "Silver prices", "query": "silver prices solar panel manufacturing demand"},
    {"name": "Aluminium prices", "query": "aluminium prices manufacturing energy transition"},
    {"name": "Polysilicon prices", "query": "polysilicon wafer solar module prices"},
    {"name": "Semiconductors", "query": "semiconductor supply chain power electronics India"},
    {"name": "Battery storage", "query": "battery energy storage India global market"},
    {"name": "Green hydrogen", "query": "green hydrogen India global policy investment"},
    {"name": "Carbon markets", "query": "carbon markets carbon credits India policy"},
    {"name": "Climate policy", "query": "global climate policy clean energy industry"},
    {"name": "Cybersecurity", "query": "energy infrastructure cybersecurity power grid"},
    {"name": "Extreme weather", "query": "extreme weather energy infrastructure supply chain"},
    {"name": "Global solar capacity", "query": "global solar capacity installations outlook"},
]


class Settings(BaseSettings):
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="SOLAR_OPENAI_MODEL")

    smtp_host: str = Field("smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    email_from_name: str = Field("Solar Industry Report", alias="SOLAR_EMAIL_FROM_NAME")
    default_recipients: str = Field(
        "alisha.kanwar@ppischool.in",
        alias="SOLAR_DEFAULT_RECIPIENTS",
    )

    report_hour_ist: int = Field(10, alias="SOLAR_REPORT_HOUR_IST")
    report_minute_ist: int = Field(0, alias="SOLAR_REPORT_MINUTE_IST")

    app_secret: str = Field("change-me-in-production", alias="APP_SECRET")
    base_url: str = Field("http://localhost:8000", alias="BASE_URL")
    db_path: str = Field("data/solar.db", alias="SOLAR_DB_PATH")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def tz(self) -> ZoneInfo:
        return IST


settings = Settings()
