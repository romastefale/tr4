from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text
from app.db.database import engine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS music_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                updated_at TEXT NOT NULL
            )
        """))


def remember_group(chat_id: int, title: str | None = None, username: str | None = None) -> None:
    ensure_tables()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO music_groups (chat_id, title, username, updated_at)
                VALUES (:chat_id, :title, :username, :updated_at)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    username=excluded.username,
                    updated_at=excluded.updated_at
            """),
            {"chat_id": int(chat_id), "title": title, "username": username, "updated_at": _now_iso()},
        )


def list_groups(limit: int = 50) -> list[dict]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT chat_id, title, username, updated_at
                FROM music_groups
                ORDER BY updated_at DESC
                LIMIT :limit
            """),
            {"limit": int(limit)},
        ).mappings().all()
    return [dict(row) for row in rows]


def is_music_group(chat_id: int) -> bool:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(text("SELECT 1 FROM music_groups WHERE chat_id=:chat_id"), {"chat_id": int(chat_id)}).first()
    return row is not None
