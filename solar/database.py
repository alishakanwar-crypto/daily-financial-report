"""SQLite persistence: recipients, ratio history, reports, articles, and AI feedback."""

from __future__ import annotations

import json
import os
from datetime import datetime

import aiosqlite

from solar.config import IST, settings


def now_ist() -> str:
    return datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipients (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ratio_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticker TEXT NOT NULL, company TEXT NOT NULL,
              statement_date TEXT NOT NULL, captured_at TEXT NOT NULL,
              ratios_json TEXT NOT NULL,
              UNIQUE(ticker, statement_date)
            );
            CREATE TABLE IF NOT EXISTS sent_articles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              url TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL, sent_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              report_date TEXT NOT NULL, status TEXT NOT NULL,
              filepath TEXT, error TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              report_date TEXT NOT NULL DEFAULT '', rating INTEGER,
              useful_sections TEXT NOT NULL DEFAULT '',
              irrelevant_items TEXT NOT NULL DEFAULT '',
              comments TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
              incorporated INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """
        )
        for email in settings.default_recipients.split(","):
            email = email.strip().lower()
            if email:
                await db.execute(
                    """INSERT OR IGNORE INTO recipients
                       (email,name,active,created_at) VALUES(?,?,1,?)""",
                    (email, "", now_ist()),
                )
        await db.commit()
    finally:
        await db.close()


async def save_ratio_snapshot(row: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ratio_snapshots
               (ticker, company, statement_date, captured_at, ratios_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker, statement_date) DO UPDATE SET
                 captured_at=excluded.captured_at, ratios_json=excluded.ratios_json""",
            (row["ticker"], row["name"], row["statement_date"], now_ist(), json.dumps(row)),
        )
        await db.commit()
    finally:
        await db.close()


async def ratio_history(ticker: str, limit: int = 8) -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT ratios_json FROM ratio_snapshots WHERE ticker=?
               ORDER BY statement_date DESC LIMIT ?""",
            (ticker, limit),
        )
        return [json.loads(r["ratios_json"]) for r in await cur.fetchall()]
    finally:
        await db.close()


async def active_recipients() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT email, name FROM recipients WHERE active=1")
        rows = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute("SELECT COUNT(*) AS count FROM recipients")
        has_saved_recipients = (await cur.fetchone())["count"] > 0
    finally:
        await db.close()
    if has_saved_recipients:
        return rows
    return [
        {"email": email.strip(), "name": ""}
        for email in settings.default_recipients.split(",")
        if email.strip()
    ]


async def add_recipient(email: str, name: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO recipients (email,name,created_at) VALUES(?,?,?)
               ON CONFLICT(email) DO UPDATE SET active=1, name=excluded.name""",
            (email, name, now_ist()),
        )
        await db.commit()
    finally:
        await db.close()


async def set_recipient_active(email: str, active: bool) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE recipients SET active=? WHERE email=?", (int(active), email))
        await db.commit()
    finally:
        await db.close()


async def article_was_sent(url: str) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM sent_articles WHERE url=?", (url,))
        return await cur.fetchone() is not None
    finally:
        await db.close()


async def mark_articles_sent(articles: list[dict], category: str) -> None:
    db = await get_db()
    try:
        for a in articles:
            await db.execute(
                "INSERT OR IGNORE INTO sent_articles(url,title,category,sent_at) VALUES(?,?,?,?)",
                (a["url"], a.get("title", ""), category, now_ist()),
            )
        await db.commit()
    finally:
        await db.close()


async def save_feedback(report_date: str, rating: int | None, useful_sections: str,
                        irrelevant_items: str, comments: str, email: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO feedback(report_date,rating,useful_sections,irrelevant_items,
               comments,email,created_at) VALUES(?,?,?,?,?,?,?)""",
            (report_date, rating, useful_sections, irrelevant_items, comments, email, now_ist()),
        )
        await db.commit()
    finally:
        await db.close()


async def feedback_memory(limit: int = 50) -> str:
    """Return recent human preferences for insertion into the AI context."""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT rating,useful_sections,irrelevant_items,comments,created_at
               FROM feedback ORDER BY id DESC LIMIT ?""", (limit,)
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    if not rows:
        return "No editor feedback has been received yet."
    lines = []
    for r in rows:
        lines.append(
            f"- Rating {r['rating'] or 'N/A'}/5; useful: {r['useful_sections'] or 'n/a'}; "
            f"irrelevant: {r['irrelevant_items'] or 'n/a'}; instruction: {r['comments'] or 'n/a'}"
        )
    return "\n".join(lines)


async def feedback_for_export() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT rating,useful_sections,irrelevant_items,comments FROM feedback ORDER BY id"
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def log_report(report_date: str, status: str, filepath: str = "", error: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO reports(report_date,status,filepath,error,created_at) VALUES(?,?,?,?,?)",
            (report_date, status, filepath, error, now_ist()),
        )
        await db.commit()
    finally:
        await db.close()
