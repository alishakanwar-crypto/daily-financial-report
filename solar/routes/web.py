"""Solar report admin, feedback, downloads, and fine-tuning export routes."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from solar.config import settings
from solar.database import (
    add_recipient,
    feedback_for_export,
    get_db,
    save_feedback,
    set_recipient_active,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/solar", tags=["Solar Industry Report"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))


def _token(request: Request, form_token: str | None = None) -> str:
    return request.query_params.get("token") or form_token or ""


def _auth(token: str) -> None:
    if settings.app_secret and settings.app_secret != "change-me-in-production" and token != settings.app_secret:
        raise HTTPException(403, "Invalid or missing access token")


def _back(
    token: str,
    status: str = "",
    destination: str = "/solar",
) -> RedirectResponse:
    if destination not in {"/solar", "/solar/mailing-list"}:
        destination = "/solar"
    args = {"token": token}
    if status:
        args["status"] = status
    return RedirectResponse(f"{destination}?{urlencode(args)}", status_code=303)


async def _recipient_rows() -> list[dict]:
    db = await get_db()
    try:
        rec = await db.execute(
            "SELECT email,name,active,created_at FROM recipients ORDER BY id DESC"
        )
        return [dict(r) for r in await rec.fetchall()]
    finally:
        await db.close()


@router.get("", response_class=HTMLResponse)
async def solar_dashboard(request: Request):
    token = _token(request)
    _auth(token)
    recipients = await _recipient_rows()
    db = await get_db()
    try:
        rep = await db.execute("SELECT report_date,status,filepath,error,created_at FROM reports ORDER BY id DESC LIMIT 12")
        reports = [dict(r) for r in await rep.fetchall()]
        fb = await db.execute("SELECT report_date,rating,comments,created_at FROM feedback ORDER BY id DESC LIMIT 10")
        feedback = [dict(r) for r in await fb.fetchall()]
    finally:
        await db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "token": token, "recipients": recipients,
        "reports": reports, "feedback": feedback,
        "schedule_time": (
            f"{settings.report_hour_ist:02d}:{settings.report_minute_ist:02d} IST"
        ),
        "status": request.query_params.get("status", ""),
    })


@router.get("/mailing-list", response_class=HTMLResponse)
async def mailing_list_dashboard(request: Request):
    token = _token(request)
    _auth(token)
    recipients = await _recipient_rows()
    return templates.TemplateResponse("mailing_list.html", {
        "request": request,
        "token": token,
        "recipients": recipients,
        "active_count": sum(1 for recipient in recipients if recipient["active"]),
        "paused_count": sum(1 for recipient in recipients if not recipient["active"]),
        "schedule_time": (
            f"{settings.report_hour_ist:02d}:{settings.report_minute_ist:02d} IST"
        ),
        "status": request.query_params.get("status", ""),
    })


def _latest_report() -> tuple[str, str] | None:
    directory = "data/solar_reports"
    if not os.path.isdir(directory):
        return None
    files = sorted(
        (filename for filename in os.listdir(directory) if filename.endswith(".pdf")),
        reverse=True,
    )
    if not files:
        return None
    path = os.path.join(directory, files[0])
    report_date = files[0].removeprefix("solar_industry_report_").removesuffix(".pdf")
    return path, report_date


async def _send_first_report(email: str, name: str) -> None:
    from solar.database import log_report
    from solar.report.email_sender import send_report
    from solar.report.generator import generate_pdf

    latest = _latest_report()
    try:
        if latest:
            path, report_date_iso = latest
            report_date = datetime.strptime(report_date_iso, "%Y-%m-%d").strftime(
                "%A, %d %B %Y"
            )
            data = {"report_date": report_date}
        else:
            path, data = await generate_pdf()
            await log_report(data["report_date_iso"], "generated", path)
        result = await send_report(
            path,
            data,
            recipients=[{"email": email, "name": name}],
        )
        if result["sent"]:
            log.info("First Solar Industry Report sent to %s", email)
        else:
            log.error(
                "First Solar Industry Report not sent to %s: %s",
                email,
                "; ".join(result["errors"]),
            )
    except Exception:
        log.exception("First Solar Industry Report delivery failed for %s", email)


@router.post("/recipients")
async def create_recipient(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    name: str = Form(""),
    token: str = Form(""),
    return_to: str = Form("/solar"),
):
    tk = _token(request, token)
    _auth(tk)
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Invalid email")
    name = name.strip()
    await add_recipient(email, name)
    background.add_task(_send_first_report, email, name)
    return _back(
        tk,
        "Recipient added; their first report is being sent now",
        return_to,
    )


@router.post("/recipients/toggle")
async def toggle_recipient(
    request: Request,
    email: str = Form(...),
    active: int = Form(...),
    token: str = Form(""),
    return_to: str = Form("/solar"),
):
    tk = _token(request, token)
    _auth(tk)
    await set_recipient_active(email.strip().lower(), bool(active))
    return _back(tk, "Recipient updated", return_to)


async def _generate_and_email() -> None:
    from datetime import datetime
    from solar.config import IST
    from solar.database import log_report
    from solar.report.email_sender import send_report
    from solar.report.generator import generate_pdf

    date = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        path, data = await generate_pdf()
        result = await send_report(path, data)
        status = "sent" if result["sent"] else "generated"
        error = "; ".join(result["errors"])
        await log_report(date, status, path, error)
    except Exception as e:  # noqa: BLE001
        await log_report(date, "failed", error=str(e))
        log.exception("Solar report generation failed")


@router.post("/generate")
async def trigger_report(request: Request, background: BackgroundTasks, token: str = Form("")):
    tk = _token(request, token)
    _auth(tk)
    background.add_task(_generate_and_email)
    return _back(tk, "Report generation started")


@router.get("/download/latest")
async def latest_report(request: Request):
    _auth(_token(request))
    directory = "data/solar_reports"
    files = sorted([f for f in os.listdir(directory) if f.endswith(".pdf")], reverse=True) if os.path.isdir(directory) else []
    if not files:
        raise HTTPException(404, "No Solar Industry Report generated yet")
    path = os.path.join(directory, files[0])
    return FileResponse(path, media_type="application/pdf", filename=files[0])


@router.get("/feedback", response_class=HTMLResponse)
async def feedback_form(request: Request, report_date: str = ""):
    return templates.TemplateResponse("feedback.html", {"request": request, "report_date": report_date})


@router.post("/feedback", response_class=HTMLResponse)
async def submit_feedback(
    request: Request,
    report_date: str = Form(""), rating: int | None = Form(None),
    useful_sections: str = Form(""), irrelevant_items: str = Form(""),
    comments: str = Form(""), email: str = Form(""),
):
    if rating is not None and rating not in range(1, 6):
        raise HTTPException(400, "Rating must be between 1 and 5")
    await save_feedback(report_date, rating, useful_sections.strip(), irrelevant_items.strip(), comments.strip(), email.strip())
    return templates.TemplateResponse("feedback_thanks.html", {"request": request})


@router.get("/feedback/export.jsonl")
async def export_fine_tuning_data(request: Request):
    """Export editor feedback in OpenAI fine-tuning JSONL format."""
    _auth(_token(request))
    rows = await feedback_for_export()
    lines = []
    for r in rows:
        user = "Curate an Indian solar industry intelligence report."
        preferred = (
            f"Editor rating: {r['rating'] or 'N/A'}/5. Useful sections: {r['useful_sections'] or 'unspecified'}. "
            f"Avoid/repair: {r['irrelevant_items'] or 'unspecified'}. Preference: {r['comments'] or 'none'}."
        )
        lines.append(json.dumps({"messages": [
            {"role": "system", "content": "You are an Indian solar competitive-intelligence analyst."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": preferred},
        ]}))
    content = "\n".join(lines) + ("\n" if lines else "")
    return StreamingResponse(iter([content]), media_type="application/jsonl", headers={
        "Content-Disposition": "attachment; filename=solar_report_feedback_finetune.jsonl"
    })
