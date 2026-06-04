from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine


DEFAULT_DEDUPE_WINDOW_SECONDS = 10 * 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_dt(value: datetime) -> str:
    return value.isoformat()


def _row_to_dict(row: Any) -> dict | None:
    if row is None:
        return None
    data = row._mapping if hasattr(row, "_mapping") else row
    return dict(data)


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radio_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_by_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_radio_templates_name ON radio_templates(name);"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radio_post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    pin INTEGER NOT NULL DEFAULT 0,
                    template_id INTEGER,
                    draft_id TEXT,
                    message_hash TEXT,
                    telegram_message_id INTEGER,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_radio_history_chat_created ON radio_post_history(chat_id, created_at);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_radio_history_hash ON radio_post_history(chat_id, message_hash, created_at);"))


def message_hash(value: str | bytes | None) -> str:
    if value is None:
        value = ""
    if isinstance(value, str):
        data = value.encode("utf-8", errors="replace")
    else:
        data = value
    return hashlib.sha256(data).hexdigest()


def create_template(*, name: str, body: str, created_by_user_id: int) -> int:
    ensure_tables()
    cleaned_name = str(name or "").strip()
    cleaned_body = str(body or "").strip()
    if not cleaned_name:
        raise ValueError("nome do template vazio")
    if not cleaned_body:
        raise ValueError("corpo do template vazio")
    if len(cleaned_name) > 80:
        raise ValueError("nome do template muito longo")
    if len(cleaned_body) > 4096:
        raise ValueError("template muito longo")
    now = utcnow()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO radio_templates (name, body, created_by_user_id, created_at, updated_at)
                VALUES (:name, :body, :created_by_user_id, :created_at, :updated_at)
                """
            ),
            {
                "name": cleaned_name,
                "body": cleaned_body,
                "created_by_user_id": int(created_by_user_id),
                "created_at": _serialize_dt(now),
                "updated_at": _serialize_dt(now),
            },
        )
        return int(result.lastrowid)


def get_template(template_id: int) -> dict | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM radio_templates WHERE id = :id"),
            {"id": int(template_id)},
        ).fetchone()
    return _row_to_dict(row)


def list_templates(*, limit: int = 10, offset: int = 0) -> list[dict]:
    ensure_tables()
    safe_limit = max(1, min(int(limit), 50))
    safe_offset = max(0, int(offset))
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM radio_templates
                 ORDER BY id DESC
                 LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": safe_limit, "offset": safe_offset},
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def delete_template(template_id: int) -> bool:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM radio_templates WHERE id = :id"), {"id": int(template_id)})
        return bool(result.rowcount)


def record_post_history(
    *,
    actor_user_id: int,
    chat_id: int,
    kind: str,
    pin: bool = False,
    template_id: int | None = None,
    draft_id: str | None = None,
    message_hash_value: str | None = None,
    telegram_message_id: int | None = None,
    status: str = "success",
    reason: str | None = None,
) -> str:
    ensure_tables()
    now = utcnow()
    event_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO radio_post_history (
                    event_id, actor_user_id, chat_id, kind, pin, template_id, draft_id,
                    message_hash, telegram_message_id, status, reason, created_at
                )
                VALUES (
                    :event_id, :actor_user_id, :chat_id, :kind, :pin, :template_id, :draft_id,
                    :message_hash, :telegram_message_id, :status, :reason, :created_at
                )
                """
            ),
            {
                "event_id": event_id,
                "actor_user_id": int(actor_user_id),
                "chat_id": int(chat_id),
                "kind": str(kind),
                "pin": 1 if pin else 0,
                "template_id": int(template_id) if template_id is not None else None,
                "draft_id": draft_id,
                "message_hash": message_hash_value,
                "telegram_message_id": int(telegram_message_id) if telegram_message_id is not None else None,
                "status": str(status),
                "reason": reason[:1000] if reason else None,
                "created_at": _serialize_dt(now),
            },
        )
    return event_id


def find_recent_duplicate(
    *,
    chat_id: int,
    message_hash_value: str,
    window_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS,
) -> dict | None:
    ensure_tables()
    since = utcnow() - timedelta(seconds=max(1, int(window_seconds)))
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT *
                  FROM radio_post_history
                 WHERE chat_id = :chat_id
                   AND message_hash = :message_hash
                   AND status = 'success'
                   AND created_at >= :since
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {
                "chat_id": int(chat_id),
                "message_hash": message_hash_value,
                "since": _serialize_dt(since),
            },
        ).fetchone()
    return _row_to_dict(row)


def list_post_history(*, chat_id: int | None = None, limit: int = 10, offset: int = 0) -> list[dict]:
    ensure_tables()
    safe_limit = max(1, min(int(limit), 50))
    safe_offset = max(0, int(offset))
    with engine.begin() as conn:
        if chat_id is None:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                      FROM radio_post_history
                     ORDER BY id DESC
                     LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": safe_limit, "offset": safe_offset},
            ).fetchall()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                      FROM radio_post_history
                     WHERE chat_id = :chat_id
                     ORDER BY id DESC
                     LIMIT :limit OFFSET :offset
                    """
                ),
                {"chat_id": int(chat_id), "limit": safe_limit, "offset": safe_offset},
            ).fetchall()
    return [dict(row._mapping) for row in rows]
