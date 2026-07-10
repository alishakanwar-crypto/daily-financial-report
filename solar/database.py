"""SQLite persistence: recipients, ratio history, reports, articles, and AI feedback."""

from __future__ import annotations

import json
import os
from datetime import datetime

import aiosqlite

from solar.config import (
    DEFAULT_COMPANIES,
    IST,
    SUPPLEMENTARY_TOPIC_CATALOG,
    Company,
    settings,
)


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
            CREATE TABLE IF NOT EXISTS tracked_companies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL, ticker TEXT UNIQUE, currency TEXT NOT NULL,
              exchange TEXT NOT NULL, listed INTEGER NOT NULL DEFAULT 1,
              website TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              listing_status TEXT NOT NULL DEFAULT 'pending',
              consecutive_failures INTEGER NOT NULL DEFAULT 0,
              last_verified_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS supplementary_topics (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL, query TEXT NOT NULL UNIQUE,
              active INTEGER NOT NULL DEFAULT 0,
              preset INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS solar_meta (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            """
        )
        seed = await db.execute(
            "SELECT 1 FROM solar_meta WHERE key='default_recipients_seeded'"
        )
        if await seed.fetchone() is None:
            for email in settings.default_recipients.split(","):
                email = email.strip().lower()
                if email:
                    await db.execute(
                        """INSERT OR IGNORE INTO recipients
                           (email,name,active,created_at) VALUES(?,?,1,?)""",
                        (email, "", now_ist()),
                    )
            await db.execute(
                """INSERT INTO solar_meta (key,value)
                   VALUES ('default_recipients_seeded','1')"""
            )
        for company in DEFAULT_COMPANIES:
            await db.execute(
                """INSERT INTO tracked_companies
                   (name,ticker,currency,exchange,listed,website,note,active,
                    listing_status,created_at,updated_at)
                   SELECT ?,?,?,?,?,?,?,?,?,?,?
                   WHERE NOT EXISTS (
                     SELECT 1 FROM tracked_companies WHERE name=?
                   )""",
                (
                    company.name,
                    company.ticker,
                    company.currency,
                    company.exchange,
                    int(company.listed),
                    company.website,
                    company.note,
                    int(company.active),
                    company.listing_status,
                    now_ist(),
                    now_ist(),
                    company.name,
                ),
            )
        for topic in SUPPLEMENTARY_TOPIC_CATALOG:
            await db.execute(
                """INSERT OR IGNORE INTO supplementary_topics
                   (name,query,active,preset,created_at,updated_at)
                   VALUES(?,?,0,1,?,?)""",
                (topic["name"], topic["query"], now_ist(), now_ist()),
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
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


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


async def delete_recipient(email: str) -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM recipients WHERE email=?", (email,))
        await db.commit()
    finally:
        await db.close()


def _company_from_row(row: aiosqlite.Row) -> Company:
    return Company(
        name=row["name"],
        ticker=row["ticker"],
        currency=row["currency"],
        exchange=row["exchange"],
        listed=bool(row["listed"]),
        website=row["website"],
        note=row["note"],
        active=bool(row["active"]),
        listing_status=row["listing_status"],
        consecutive_failures=row["consecutive_failures"],
    )


async def tracked_companies(active_only: bool = True) -> list[Company]:
    db = await get_db()
    try:
        query = "SELECT * FROM tracked_companies"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY id"
        cur = await db.execute(query)
        return [_company_from_row(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def company_rows() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id,name,ticker,currency,exchange,listed,website,note,active,
                      listing_status,consecutive_failures,last_verified_at,
                      created_at,updated_at
               FROM tracked_companies ORDER BY active DESC, id"""
        )
        return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def add_company(
    name: str,
    ticker: str,
    currency: str,
    exchange: str,
    website: str = "",
    note: str = "",
) -> None:
    db = await get_db()
    try:
        timestamp = now_ist()
        await db.execute(
            """INSERT INTO tracked_companies
               (name,ticker,currency,exchange,listed,website,note,active,
                listing_status,consecutive_failures,created_at,updated_at)
               VALUES(?,?,?,?,1,?,?,1,'pending',0,?,?)
               ON CONFLICT(ticker) DO UPDATE SET
                 name=excluded.name, currency=excluded.currency,
                 exchange=excluded.exchange, website=excluded.website,
                 note=excluded.note, listed=1, active=1,
                 listing_status='pending', consecutive_failures=0,
                 updated_at=excluded.updated_at""",
            (name, ticker, currency, exchange, website, note, timestamp, timestamp),
        )
        await db.commit()
    finally:
        await db.close()


async def set_company_active(company_id: int, active: bool) -> None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT listed FROM tracked_companies WHERE id=?",
            (company_id,),
        )
        row = await cur.fetchone()
        if row:
            status = "pending" if active and row["listed"] else "private"
            if not active:
                status = "manually_removed"
            await db.execute(
                """UPDATE tracked_companies
                   SET active=?, listing_status=?, consecutive_failures=0,
                       updated_at=?
                   WHERE id=?""",
                (int(active), status, now_ist(), company_id),
            )
            await db.commit()
    finally:
        await db.close()


async def apply_listing_checks(
    price_rows: list[dict],
    delisting_threshold: int = 3,
) -> list[str]:
    deactivated = []
    db = await get_db()
    try:
        for price in price_rows:
            ticker = price.get("ticker")
            if not ticker:
                continue
            if price.get("close") is not None:
                await db.execute(
                    """UPDATE tracked_companies
                       SET listing_status='listed', consecutive_failures=0,
                           last_verified_at=?, updated_at=?
                       WHERE ticker=? AND active=1""",
                    (now_ist(), now_ist(), ticker),
                )
                continue
            if not price.get("delisting_signal"):
                continue
            cur = await db.execute(
                """SELECT id,name,consecutive_failures
                   FROM tracked_companies WHERE ticker=? AND active=1""",
                (ticker,),
            )
            company = await cur.fetchone()
            if not company:
                continue
            failures = company["consecutive_failures"] + 1
            auto_delisted = failures >= delisting_threshold
            await db.execute(
                """UPDATE tracked_companies
                   SET active=?, listing_status=?, consecutive_failures=?,
                       last_verified_at=?, updated_at=?
                   WHERE id=?""",
                (
                    int(not auto_delisted),
                    "auto_delisted" if auto_delisted else "possible_delisting",
                    failures,
                    now_ist(),
                    now_ist(),
                    company["id"],
                ),
            )
            if auto_delisted:
                deactivated.append(ticker)
        await db.commit()
    finally:
        await db.close()
    return deactivated


async def supplementary_topic_rows() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id,name,query,active,preset,created_at,updated_at
               FROM supplementary_topics
               ORDER BY active DESC, preset DESC, name"""
        )
        return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def active_supplementary_topics() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id,name,query,preset FROM supplementary_topics
               WHERE active=1 ORDER BY name"""
        )
        return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def add_supplementary_topic(name: str, query: str) -> None:
    db = await get_db()
    try:
        timestamp = now_ist()
        await db.execute(
            """INSERT INTO supplementary_topics
               (name,query,active,preset,created_at,updated_at)
               VALUES(?,?,1,0,?,?)
               ON CONFLICT(query) DO UPDATE SET
                 name=excluded.name, active=1, updated_at=excluded.updated_at""",
            (name, query, timestamp, timestamp),
        )
        await db.commit()
    finally:
        await db.close()


async def set_supplementary_topic_active(topic_id: int, active: bool) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE supplementary_topics SET active=?,updated_at=? WHERE id=?",
            (int(active), now_ist(), topic_id),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_supplementary_topic(topic_id: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM supplementary_topics WHERE id=? AND preset=0",
            (topic_id,),
        )
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
