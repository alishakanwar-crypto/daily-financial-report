"""Email the Solar Industry Intelligence PDF to active recipients."""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib

from solar.config import settings
from solar.database import active_recipients

log = logging.getLogger(__name__)

EMAIL_HTML = """<!doctype html><html><body style="margin:0;background:#eef6f0;font-family:Arial,sans-serif;color:#173326">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px">
<table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 18px #cbded0">
<tr><td style="padding:34px;background:linear-gradient(135deg,#06472b,#15924e);color:#fff"><div style="font-size:11px;letter-spacing:2px">INDIAN SOLAR COMPETITIVE INTELLIGENCE</div><h1 style="margin:10px 0 4px;font-size:28px">Solar Industry Report</h1><div style="color:#d8f3df">{date}</div></td></tr>
<tr><td style="padding:28px;line-height:1.55"><p>Your latest AI-curated report is attached as a clickable PDF.</p>
<table width="100%" style="background:#f2f9f4;border:1px solid #d5eadb;border-radius:8px;padding:14px;font-size:14px"><tr><td>
<b>Inside:</b><br>• Previous trading day open, close and average prices<br>• Comparative valuation, financial and cash-flow ratios<br>• Last-statement dates and automatically maintained ratio history<br>• Indian solar news from the last 24 hours<br>• Government policy and regulatory radar<br>• Feedback link that teaches the AI your preferences
</td></tr></table>
<p style="font-size:13px;color:#5a7465">Tracking ReNew, Waaree, Premier Energies, Vikram Solar and Emmvee.</p></td></tr>
<tr><td style="padding:18px 28px;background:#f7faf8;color:#758b7e;font-size:11px">Solar Industry Intelligence • For competitive analysis, not investment advice.</td></tr>
</table></td></tr></table></body></html>"""


async def send_report(pdf_path: str, report_data: dict) -> dict:
    if not settings.smtp_user or not settings.smtp_password:
        return {"sent": 0, "failed": 0, "errors": ["SMTP not configured"]}
    recipients = await active_recipients()
    if not recipients:
        return {"sent": 0, "failed": 0, "errors": ["No active recipients"]}

    with open(pdf_path, "rb") as f:
        attachment = f.read()
    result = {"sent": 0, "failed": 0, "errors": []}
    for recipient in recipients:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"Indian Solar Industry Intelligence — {report_data['report_date']}"
            msg["From"] = formataddr((settings.email_from_name, settings.smtp_user))
            msg["To"] = recipient["email"]
            msg.set_content(f"Your Solar Industry Report for {report_data['report_date']} is attached.")
            msg.add_alternative(EMAIL_HTML.format(date=report_data["report_date"]), subtype="html")
            msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=os.path.basename(pdf_path))
            await aiosmtplib.send(
                msg, hostname=settings.smtp_host, port=settings.smtp_port,
                username=settings.smtp_user, password=settings.smtp_password, start_tls=True,
            )
            result["sent"] += 1
        except Exception as e:  # noqa: BLE001
            result["failed"] += 1
            result["errors"].append(f"{recipient['email']}: {e}")
            log.error(f"Email failed for {recipient['email']}: {e}")
    return result
