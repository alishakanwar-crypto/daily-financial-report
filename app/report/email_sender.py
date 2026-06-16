"""Send the daily report PDF via email (SMTP / aiosmtplib)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib

from app.config import settings, IST
from app.database import get_active_recipients

log = logging.getLogger(__name__)

EMAIL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
  .wrapper {{ max-width: 600px; margin: 20px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%); padding: 32px 28px; color: #fff; }}
  .header h1 {{ font-size: 24px; margin: 0 0 4px 0; font-weight: 800; }}
  .header .sub {{ color: #94a3b8; font-size: 14px; }}
  .body {{ padding: 28px; color: #334155; font-size: 15px; line-height: 1.6; }}
  .body p {{ margin: 0 0 14px 0; }}
  .highlights {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }}
  .highlights h3 {{ font-size: 14px; color: #1e40af; margin: 0 0 8px 0; }}
  .highlights ul {{ margin: 0; padding-left: 18px; font-size: 13px; color: #475569; }}
  .highlights li {{ margin-bottom: 4px; }}
  .cta {{ display: inline-block; margin: 16px 0; padding: 12px 24px; background: #1d4ed8; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px; }}
  .footer {{ padding: 20px 28px; font-size: 11px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  .footer a {{ color: #64748b; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Daily Market Pulse</h1>
    <div class="sub">{date} — Your daily financial intelligence brief</div>
  </div>
  <div class="body">
    <p>Good morning! Your curated market report is attached.</p>
    <div class="highlights">
      <h3>Today's Highlights</h3>
      <ul>
        <li><strong>Indian Markets:</strong> {indian_stocks} stocks tracked with DuPont analysis</li>
        <li><strong>US Markets:</strong> {us_stocks} stocks tracked with full metrics</li>
        <li><strong>Commodities:</strong> Gold, Silver, Oil — daily/monthly/yearly changes</li>
        <li><strong>Deep Dive:</strong> {deep_indian} (India) &amp; {deep_us} (US) annual financials</li>
        <li><strong>News:</strong> AI-curated articles across Indian, US &amp; international markets</li>
      </ul>
    </div>
    <p>Open the attached PDF for the complete interactive report with clickable news links, DuPont ratios, and financial statement analysis.</p>
  </div>
  <div class="footer">
    Daily Market Pulse · AI-curated financial intelligence<br>
    Data: Yahoo Finance, BSE, SEC EDGAR · News: FT, WSJ, ET, Bloomberg, Reuters<br>
    <em>This report is for informational purposes only.</em><br>
    <a href="{unsubscribe_url}">Unsubscribe</a>
  </div>
</div>
</body>
</html>
"""


async def send_report(pdf_path: str, report_data: dict | None = None) -> dict:
    """Email the report PDF to all active recipients.

    Returns: {"sent": int, "failed": int, "errors": [...]}
    """
    if not settings.smtp_user or not settings.smtp_password:
        log.error("SMTP credentials not configured – skipping email send")
        return {"sent": 0, "failed": 0, "errors": ["SMTP not configured"]}

    recipients = await get_active_recipients()
    if not recipients:
        log.warning("No active recipients – skipping email send")
        return {"sent": 0, "failed": 0, "errors": ["No recipients"]}

    today = datetime.now(IST).strftime("%B %d, %Y")

    # Read PDF attachment
    with open(pdf_path, "rb") as f:
        pdf_data = f.read()
    pdf_filename = os.path.basename(pdf_path)

    body_html = EMAIL_HTML_TEMPLATE.format(
        date=today,
        indian_stocks=report_data.get("indian_count", 15) if report_data else 15,
        us_stocks=report_data.get("us_count", 15) if report_data else 15,
        deep_indian=report_data.get("deep_indian", "Top Indian Co") if report_data else "Top Indian Co",
        deep_us=report_data.get("deep_us", "Top US Co") if report_data else "Top US Co",
        unsubscribe_url=f"{settings.base_url}/unsubscribe",
    )

    sent = 0
    failed = 0
    errors: list[str] = []

    for recip in recipients:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"📊 Daily Market Pulse – {today}"
            msg["From"] = formataddr((settings.email_from_name, settings.smtp_user))
            msg["To"] = recip["email"]

            msg.set_content(f"Your Daily Market Pulse report for {today} is attached.")
            msg.add_alternative(body_html, subtype="html")
            msg.add_attachment(
                pdf_data,
                maintype="application",
                subtype="pdf",
                filename=pdf_filename,
            )

            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            sent += 1
            log.info(f"Report sent to {recip['email']}")
        except Exception as e:
            failed += 1
            errors.append(f"{recip['email']}: {e}")
            log.error(f"Failed to send to {recip['email']}: {e}")

    return {"sent": sent, "failed": failed, "errors": errors}
