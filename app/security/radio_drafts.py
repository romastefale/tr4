from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine


DEFAULT_TTL_SECONDS = 30 * 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radio_drafts (
                    id TEXT PRIMARY KEY,
                    actor_user_id INTEGER NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT,
                    source_chat_id INTEGER,
                    source_message_id INTEGER,
                    pin INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    sent_message_id INTEGER,
                    error TEXT,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )


def _serialize_dt(value: datetime) -> str:
    return value.isoformat()


def _row_to_dict(row: Any) -> dict | None:
    if row is None:
        return None
    data = row._mapping if hasattr(row, "_mapping") else row
    return dict(data)


def create_text_draft(
    *,
    actor_user_id: int,
    target_chat_id: int,
    text_value: str,
    pin: bool = False,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    ensure_tables()
    now = utcnow()
    draft_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO radio_drafts (
                    id, actor_user_id, target_chat_id, kind, text, pin,
                    status, created_at, expires_at, updated_at
                )
                VALUES (
                    :id, :actor_user_id, :target_chat_id, 'text', :text, :pin,
                    'pending', :created_at, :expires_at, :updated_at
                )
                """
            ),
            {
                "id": draft_id,
                "actor_user_id": int(actor_user_id),
                "target_chat_id": int(target_chat_id),
                "text": text_value,
                "pin": 1 if pin else 0,
                "created_at": _serialize_dt(now),
                "expires_at": _serialize_dt(now + timedelta(seconds=ttl_seconds)),
                "updated_at": _serialize_dt(now),
            },
        )
    return draft_id


def create_media_draft(
    *,
    actor_user_id: int,
    target_chat_id: int,
    source_chat_id: int,
    source_message_id: int,
    pin: bool = False,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    ensure_tables()
    now = utcnow()
    draft_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO radio_drafts (
                    id, actor_user_id, target_chat_id, kind, source_chat_id,
                    source_message_id, pin, status, created_at, expires_at, updated_at
                )
                VALUES (
                    :id, :actor_user_id, :target_chat_id, 'media', :source_chat_id,
                    :source_message_id, :pin, 'pending', :created_at, :expires_at, :updated_at
                )
                """
            ),
            {
                "id": draft_id,
                "actor_user_id": int(actor_user_id),
                "target_chat_id": int(target_chat_id),
                "source_chat_id": int(source_chat_id),
                "source_message_id": int(source_message_id),
                "pin": 1 if pin else 0,
                "created_at": _serialize_dt(now),
                "expires_at": _serialize_dt(now + timedelta(seconds=ttl_seconds)),
                "updated_at": _serialize_dt(now),
            },
        )
    return draft_id


def get_draft(draft_id: str) -> dict | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM radio_drafts WHERE id = :id"),
            {"id": draft_id},
        ).fetchone()
    return _row_to_dict(row)


def is_draft_expired(draft: dict, *, now: datetime | None = None) -> bool:
    expires_raw = str(draft.get("expires_at") or "")
    if not expires_raw:
        return True
    try:
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (now or utcnow()) > expires_at


def mark_sent(draft_id: str, *, sent_message_id: int | None = None) -> None:
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE radio_drafts
                   SET status = 'sent',
                       sent_message_id = :sent_message_id,
                       updated_at = :updated_at
                 WHERE id = :id
                """
            ),
            {"id": draft_id, "sent_message_id": sent_message_id, "updated_at": _serialize_dt(now)},
        )


def mark_cancelled(draft_id: str) -> None:
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE radio_drafts
                   SET status = 'cancelled',
                       updated_at = :updated_at
                 WHERE id = :id
                """
            ),
            {"id": draft_id, "updated_at": _serialize_dt(now)},
        )


def mark_error(draft_id: str, *, error: str) -> None:
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE radio_drafts
                   SET status = 'error',
                       error = :error,
                       updated_at = :updated_at
                 WHERE id = :id
                """
            ),
            {"id": draft_id, "error": error[:1000], "updated_at": _serialize_dt(now)},
        )


def purge_expired(now: datetime | None = None) -> int:
    current = now or utcnow()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                DELETE FROM radio_drafts
                 WHERE status IN ('pending', 'cancelled', 'error')
                   AND expires_at < :now
                """
            ),
            {"now": _serialize_dt(current)},
        )
        return int(result.rowcount or 0)
