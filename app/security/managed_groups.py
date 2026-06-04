from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.config.settings import MANAGED_GROUP_IDS, ROOT_USER_ID
from app.db.database import engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables() -> None:
    """Create managed-group tables used by Phase 2.

    `tigrao_groups` remains the discovery table for groups the bot has seen.
    `managed_groups` is the explicit allowlist for moderation/BTB/destructive
    actions. A known group is not automatically managed.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS managed_groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    added_by_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    notes TEXT
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS managed_group_status (
                    chat_id INTEGER PRIMARY KEY,
                    bot_status TEXT,
                    can_delete_messages INTEGER,
                    can_restrict_members INTEGER,
                    can_pin_messages INTEGER,
                    can_manage_tags INTEGER,
                    can_change_info INTEGER,
                    can_promote_members INTEGER,
                    can_invite_users INTEGER,
                    can_manage_topics INTEGER,
                    can_manage_video_chats INTEGER,
                    last_checked_at DATETIME,
                    last_error TEXT
                );
                """
            )
        )


def upsert_managed_group(
    chat_id: int,
    title: str | None = None,
    *,
    enabled: bool = True,
    added_by_user_id: int | None = None,
    notes: str | None = None,
) -> None:
    ensure_tables()
    now = utcnow()
    actor = added_by_user_id or ROOT_USER_ID or 0
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO managed_groups (
                    chat_id, title, enabled, added_by_user_id, created_at, updated_at, notes
                ) VALUES (
                    :chat_id, :title, :enabled, :added_by_user_id, :created_at, :updated_at, :notes
                )
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = COALESCE(excluded.title, managed_groups.title),
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    notes = COALESCE(excluded.notes, managed_groups.notes)
                """
            ),
            {
                "chat_id": int(chat_id),
                "title": title or str(chat_id),
                "enabled": 1 if enabled else 0,
                "added_by_user_id": actor,
                "created_at": now,
                "updated_at": now,
                "notes": notes,
            },
        )


def bootstrap_from_env() -> None:
    """Insert TR3_MANAGED_GROUP_IDS into the managed allowlist.

    This is idempotent. Titles are placeholders until the bot observes the
    group or a later panel updates them.
    """
    ensure_tables()
    for chat_id in MANAGED_GROUP_IDS:
        upsert_managed_group(
            int(chat_id),
            title=str(chat_id),
            enabled=True,
            added_by_user_id=ROOT_USER_ID or 0,
            notes="bootstrap:TR3_MANAGED_GROUP_IDS",
        )


def is_managed_group(chat_id: int | str | None) -> bool:
    if chat_id is None:
        return False
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT enabled FROM managed_groups WHERE chat_id=:chat_id LIMIT 1"),
            {"chat_id": cid},
        ).first()
    return bool(row and int(row[0]) == 1)


def list_managed_groups(limit: int = 100) -> list[dict[str, Any]]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT chat_id, title, enabled, added_by_user_id, created_at, updated_at, notes
                FROM managed_groups
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": int(limit)},
        ).mappings().all()
    return [dict(row) for row in rows]


def update_group_status(
    *,
    chat_id: int,
    bot_status: str,
    can_delete_messages: bool | None = None,
    can_restrict_members: bool | None = None,
    can_pin_messages: bool | None = None,
    can_manage_tags: bool | None = None,
    can_change_info: bool | None = None,
    can_promote_members: bool | None = None,
    can_invite_users: bool | None = None,
    can_manage_topics: bool | None = None,
    can_manage_video_chats: bool | None = None,
    last_error: str | None = None,
) -> None:
    ensure_tables()

    def b(value: bool | None) -> int | None:
        return None if value is None else (1 if value else 0)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO managed_group_status (
                    chat_id, bot_status, can_delete_messages, can_restrict_members,
                    can_pin_messages, can_manage_tags, can_change_info,
                    can_promote_members, can_invite_users, can_manage_topics,
                    can_manage_video_chats, last_checked_at, last_error
                ) VALUES (
                    :chat_id, :bot_status, :can_delete_messages, :can_restrict_members,
                    :can_pin_messages, :can_manage_tags, :can_change_info,
                    :can_promote_members, :can_invite_users, :can_manage_topics,
                    :can_manage_video_chats, :last_checked_at, :last_error
                )
                ON CONFLICT(chat_id) DO UPDATE SET
                    bot_status = excluded.bot_status,
                    can_delete_messages = excluded.can_delete_messages,
                    can_restrict_members = excluded.can_restrict_members,
                    can_pin_messages = excluded.can_pin_messages,
                    can_manage_tags = excluded.can_manage_tags,
                    can_change_info = excluded.can_change_info,
                    can_promote_members = excluded.can_promote_members,
                    can_invite_users = excluded.can_invite_users,
                    can_manage_topics = excluded.can_manage_topics,
                    can_manage_video_chats = excluded.can_manage_video_chats,
                    last_checked_at = excluded.last_checked_at,
                    last_error = excluded.last_error
                """
            ),
            {
                "chat_id": int(chat_id),
                "bot_status": bot_status,
                "can_delete_messages": b(can_delete_messages),
                "can_restrict_members": b(can_restrict_members),
                "can_pin_messages": b(can_pin_messages),
                "can_manage_tags": b(can_manage_tags),
                "can_change_info": b(can_change_info),
                "can_promote_members": b(can_promote_members),
                "can_invite_users": b(can_invite_users),
                "can_manage_topics": b(can_manage_topics),
                "can_manage_video_chats": b(can_manage_video_chats),
                "last_checked_at": utcnow(),
                "last_error": (last_error or "")[:500] if last_error else None,
            },
        )
