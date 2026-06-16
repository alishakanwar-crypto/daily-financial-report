"""Dashboard routes for mailing-list management and manual report triggers."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Query, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import (
    get_active_recipients,
    add_recipient,
    remove_recipient,
    toggle_recipient,
)

log = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)


def _verify_token(token: str = Query(None, alias="token")):
    """Require ?token=<APP_SECRET> on protected dashboard routes."""
    if settings.app_secret and settings.app_secret != "change-me-in-production":
        if token != settings.app_secret:
            raise HTTPException(403, "Invalid or missing access token. Append ?token=<APP_SECRET> to the URL.")


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, _: None = Depends(_verify_token)):
    """Render the mailing-list management dashboard."""
    from app.database import get_db

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, email, name, active, created_at FROM recipients ORDER BY created_at DESC"
        )
        recipients = [dict(r) for r in await cursor.fetchall()]

        cursor2 = await db.execute(
            "SELECT date, status, filepath FROM report_log ORDER BY date DESC LIMIT 10"
        )
        recent_reports = [dict(r) for r in await cursor2.fetchall()]
    finally:
        await db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "recipients": recipients,
            "recent_reports": recent_reports,
        },
    )


@router.post("/add-recipient")
async def handle_add_recipient(email: str = Form(...), name: str = Form(""), _: None = Depends(_verify_token)):
    """Add a new email to the mailing list."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    await add_recipient(email, name.strip())
    return RedirectResponse("/", status_code=303)


@router.post("/remove-recipient")
async def handle_remove_recipient(email: str = Form(...), _: None = Depends(_verify_token)):
    """Remove an email from the mailing list."""
    await remove_recipient(email.strip().lower())
    return RedirectResponse("/", status_code=303)


@router.post("/toggle-recipient")
async def handle_toggle_recipient(email: str = Form(...), active: str = Form("1"), _: None = Depends(_verify_token)):
    """Toggle active/inactive status."""
    await toggle_recipient(email.strip().lower(), active == "1")
    return RedirectResponse("/", status_code=303)


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(request: Request, email: str = ""):
    return templates.TemplateResponse("unsubscribe.html", {"request": request, "email": email})


@router.post("/unsubscribe")
async def handle_unsubscribe(email: str = Form(...)):
    await toggle_recipient(email.strip().lower(), False)
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:60px;'>"
        "<h2>Unsubscribed</h2><p>You have been removed from the mailing list.</p>"
        "</body></html>"
    )


@router.post("/trigger-report")
async def trigger_report_now(_: None = Depends(_verify_token)):
    """Manually trigger report generation & sending."""
    from app.report.generator import generate_pdf
    from app.report.email_sender import send_report
    from app.database import log_report
    from datetime import datetime
    from app.config import IST

    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        log.info("Manual report trigger started")
        pdf_path = await generate_pdf()
        result = await send_report(pdf_path)
        await log_report(date_str, "sent", pdf_path)
        return {"status": "ok", "pdf": pdf_path, **result}
    except Exception as e:
        await log_report(date_str, "failed", error=str(e))
        log.error(f"Report generation failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/download-latest")
async def download_latest(_: None = Depends(_verify_token)):
    """Download the most recent generated PDF."""
    report_dir = "data/reports"
    if not os.path.isdir(report_dir):
        raise HTTPException(404, "No reports generated yet")
    files = sorted(
        [f for f in os.listdir(report_dir) if f.endswith(".pdf")],
        reverse=True,
    )
    if not files:
        raise HTTPException(404, "No reports found")
    return FileResponse(
        os.path.join(report_dir, files[0]),
        media_type="application/pdf",
        filename=files[0],
    )
