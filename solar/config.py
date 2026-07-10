"""Configuration for the Solar Industry Report system."""

from __future__ import annotations

import json
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
    ):
        self.name = name
        self.ticker = ticker
        self.currency = currency
        self.exchange = exchange
        self.listed = listed
        self.website = website
        self.note = note


# --- The competitive set: Indian solar technology companies ---
COMPANIES: List[Company] = [
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
        None,
        "INR",
        "Unlisted",
        listed=False,
        website="https://www.emmvee.com",
        note="Private/unlisted (IPO filed) — price & market ratios unavailable; tracked via news.",
    ),
]


def listed_companies() -> List[Company]:
    return [c for c in COMPANIES if c.listed and c.ticker]


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

    report_hour_ist: int = Field(7, alias="SOLAR_REPORT_HOUR_IST")
    report_minute_ist: int = Field(30, alias="SOLAR_REPORT_MINUTE_IST")

    app_secret: str = Field("change-me-in-production", alias="APP_SECRET")
    base_url: str = Field("http://localhost:8000", alias="BASE_URL")
    db_path: str = Field("data/solar.db", alias="SOLAR_DB_PATH")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def tz(self) -> ZoneInfo:
        return IST


settings = Settings()
