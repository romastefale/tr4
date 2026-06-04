from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS private_panels (
                    actor_user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    panel_type TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ephemeral_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    delete_after DATETIME,
                    reason TEXT,
                    created_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ephemeral_messages_actor ON ephemeral_messages(actor_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ephemeral_messages_delete_after ON ephemeral_messages(delete_after)"))


def upsert_panel(*, actor_user_id: int, chat_id: int, message_id: int, panel_type: str = "tigrao") -> None:
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO private_panels (
                    actor_user_id, chat_id, message_id, panel_type, created_at, updated_at
                ) VALUES (
                    :actor_user_id, :chat_id, :message_id, :panel_type, :created_at, :updated_at
                )
                ON CONFLICT(actor_user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    message_id = excluded.message_id,
                    panel_type = excluded.panel_type,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "actor_user_id": int(actor_user_id),
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "panel_type": panel_type,
                "created_at": now,
                "updated_at": now,
            },
        )


def get_panel(actor_user_id: int) -> dict[str, Any] | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT actor_user_id, chat_id, message_id, panel_type, created_at, updated_at
                FROM private_panels
                WHERE actor_user_id=:actor_user_id
                LIMIT 1
                """
            ),
            {"actor_user_id": int(actor_user_id)},
        ).mappings().first()
    return dict(row) if row else None


def remember_ephemeral(
    *,
    actor_user_id: int,
    chat_id: int,
    message_id: int,
    reason: str | None = None,
    ttl_seconds: int | None = 15 * 60,
) -> None:
    ensure_tables()
    now = utcnow()
    delete_after = now + timedelta(seconds=int(ttl_seconds)) if ttl_seconds is not None else None
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ephemeral_messages (
                    actor_user_id, chat_id, message_id, delete_after, reason, created_at
                ) VALUES (
                    :actor_user_id, :chat_id, :message_id, :delete_after, :reason, :created_at
                )
                """
            ),
            {
                "actor_user_id": int(actor_user_id),
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "delete_after": delete_after,
                "reason": reason,
                "created_at": now,
            },
        )


def list_ephemeral(actor_user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, actor_user_id, chat_id, message_id, delete_after, reason, created_at
                FROM ephemeral_messages
                WHERE actor_user_id=:actor_user_id
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"actor_user_id": int(actor_user_id), "limit": int(limit)},
        ).mappings().all()
    return [dict(row) for row in rows]


def delete_ephemeral_record(row_id: int) -> None:
    ensure_tables()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ephemeral_messages WHERE id=:id"), {"id": int(row_id)})


async def cleanup_ephemeral_messages(bot, actor_user_id: int, *, limit: int = 25) -> int:
    """Best-effort cleanup for private-panel clutter.

    Failures are ignored because Telegram may reject deletes for old messages.
    Records are removed regardless so the table remains bounded.
    """
    deleted = 0
    for row in list_ephemeral(actor_user_id, limit=limit):
        try:
            await bot.delete_message(int(row["chat_id"]), int(row["message_id"]))
            deleted += 1
        except Exception:
            pass
        finally:
            delete_ephemeral_record(int(row["id"]))
    return deleted
