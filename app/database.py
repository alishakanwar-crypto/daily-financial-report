"""SQLite database for mailing list and article deduplication."""

import aiosqlite
import os
from datetime import datetime
from app.config import settings, IST

DB_PATH = settings.db_path


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT    NOT NULL UNIQUE,
                name        TEXT    NOT NULL DEFAULT '',
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sent_articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT    NOT NULL,
                title       TEXT    NOT NULL DEFAULT '',
                sent_date   TEXT    NOT NULL,
                segment     TEXT    NOT NULL DEFAULT '',
                UNIQUE(url)
            );

            CREATE TABLE IF NOT EXISTS report_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL UNIQUE,
                status      TEXT    NOT NULL DEFAULT 'pending',
                filepath    TEXT,
                error       TEXT,
                created_at  TEXT    NOT NULL
            );
            """
        )
        await db.commit()
    finally:
        await db.close()


async def get_active_recipients() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, email, name FROM recipients WHERE active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


def _now_ist_str() -> str:
    return datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")


def _today_ist_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


async def add_recipient(email: str, name: str = "") -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO recipients (email, name, created_at) VALUES (?, ?, ?)",
            (email, name, _now_ist_str()),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def remove_recipient(email: str) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM recipients WHERE email = ?", (email,))
        await db.commit()
        return True
    finally:
        await db.close()


async def toggle_recipient(email: str, active: bool) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE recipients SET active = ? WHERE email = ?", (1 if active else 0, email)
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def is_article_sent(url: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT 1 FROM sent_articles WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return row is not None
    finally:
        await db.close()


async def mark_articles_sent(articles: list[dict], segment: str):
    db = await get_db()
    try:
        for art in articles:
            await db.execute(
                "INSERT OR IGNORE INTO sent_articles (url, title, segment, sent_date) VALUES (?, ?, ?, ?)",
                (art["url"], art.get("title", ""), segment, _today_ist_str()),
            )
        await db.commit()
    finally:
        await db.close()


async def log_report(date_str: str, status: str, filepath: str = "", error: str = ""):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO report_log (date, status, filepath, error, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET status=?, filepath=?, error=?""",
            (date_str, status, filepath, error, _now_ist_str(), status, filepath, error),
        )
        await db.commit()
    finally:
        await db.close()
