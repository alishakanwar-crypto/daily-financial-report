"""Daily Market Pulse — FastAPI application with APScheduler."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings, IST
from app.database import init_db, log_report
from app.routes.dashboard import router as dashboard_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_report_job():
    """The daily job that generates the PDF and emails it."""
    from app.report.generator import generate_pdf
    from app.report.email_sender import send_report

    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%Y-%m-%d")
    log.info(f"=== Scheduled report generation started ({now_ist.strftime('%d-%m-%Y %H:%M:%S IST')}) ===")
    try:
        pdf_path = await generate_pdf()
        result = await send_report(pdf_path)
        await log_report(date_str, "sent", pdf_path)
        log.info(f"Report sent: {result}")
    except Exception as e:
        await log_report(date_str, "failed", error=str(e))
        log.error(f"Scheduled report failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    await init_db()
    log.info("Database initialized")

    # Schedule the daily report in IST
    trigger = CronTrigger(
        hour=settings.report_hour_ist,
        minute=settings.report_minute_ist,
        timezone="Asia/Kolkata",
    )
    scheduler.add_job(scheduled_report_job, trigger, id="daily_report", replace_existing=True)
    scheduler.start()
    log.info(
        f"Scheduler started — report at {settings.report_hour_ist:02d}:{settings.report_minute_ist:02d} IST daily"
    )

    yield

    scheduler.shutdown(wait=False)
    log.info("Scheduler shut down")


app = FastAPI(
    title="Daily Market Pulse",
    description="Automated daily financial report generator & mailer",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Routes
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "scheduler_running": scheduler.running,
        "next_report": str(scheduler.get_job("daily_report").next_run_time)
        if scheduler.get_job("daily_report")
        else None,
    }
