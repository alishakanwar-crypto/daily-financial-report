"""Central configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
from zoneinfo import ZoneInfo
import json, os


class Settings(BaseSettings):
    # --- OpenAI ---
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")

    # --- Email / SMTP ---
    smtp_host: str = Field("smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    email_from_name: str = Field("Daily Market Pulse", alias="EMAIL_FROM_NAME")

    # --- Report (schedule in IST) ---
    report_hour_ist: int = Field(7, alias="REPORT_HOUR_IST")
    report_minute_ist: int = Field(0, alias="REPORT_MINUTE_IST")
    timezone: str = Field("Asia/Kolkata", alias="TIMEZONE")

    # --- App ---
    app_secret: str = Field("change-me-in-production", alias="APP_SECRET")
    base_url: str = Field("http://localhost:8000", alias="BASE_URL")
    db_path: str = Field("data/app.db", alias="DB_PATH")

    # --- Stock lists (JSON arrays of ticker symbols) ---
    indian_stocks_json: str = Field(
        '["RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",'
        '"BHARTIARTL.NS","SBIN.NS","ITC.NS","LT.NS","AXISBANK.NS",'
        '"KOTAKBANK.NS","HINDUNILVR.NS","SUNPHARMA.NS","ADANIENT.NS","BAJFINANCE.NS"]',
        alias="INDIAN_STOCKS",
    )
    us_stocks_json: str = Field(
        '["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B",'
        '"JPM","JNJ","V","UNH","WMT","LLY","MA"]',
        alias="US_STOCKS",
    )

    @property
    def indian_stocks(self) -> List[str]:
        return json.loads(self.indian_stocks_json)

    @property
    def us_stocks(self) -> List[str]:
        return json.loads(self.us_stocks_json)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Canonical IST timezone object
IST = ZoneInfo("Asia/Kolkata")
