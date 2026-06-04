from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import text

from app.db.database import engine
from app.security.audit import log_audit_event
from app.security.bot_rights import get_bot_rights
from app.security.managed_groups import list_managed_groups, update_group_status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS adeus_recovery_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL UNIQUE,
                actor_user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                total_groups INTEGER NOT NULL DEFAULT 0,
                prepared_count INTEGER NOT NULL DEFAULT 0,
                failed_prepare_count INTEGER NOT NULL DEFAULT 0,
                left_count INTEGER NOT NULL DEFAULT 0,
                failed_leave_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                confirmed_at DATETIME,
                executed_at DATETIME,
                expires_at DATETIME
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS adeus_recovery_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT,
                bot_status_before TEXT,
                can_invite_users_before INTEGER,
                invite_link TEXT,
                invite_expires_at DATETIME,
                prepare_status TEXT NOT NULL,
                leave_status TEXT,
                rejoin_status TEXT,
                last_error TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE(operation_id, chat_id)
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_adeus_items_operation ON adeus_recovery_items(operation_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_adeus_items_chat ON adeus_recovery_items(chat_id)"))


def _enabled_managed_groups(limit: int = 10000) -> list[dict[str, Any]]:
    return [g for g in list_managed_groups(limit=limit) if int(g.get("enabled") or 0) == 1]


def create_recovery_operation(*, actor_user_id: int, ttl_hours: int = 168) -> str:
    ensure_tables()
    operation_id = secrets.token_urlsafe(12)
    groups = _enabled_managed_groups()
    now = utcnow()
    expires_at = now + timedelta(hours=ttl_hours)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO adeus_recovery_operations (
                operation_id, actor_user_id, status, total_groups,
                created_at, expires_at
            ) VALUES (
                :operation_id, :actor_user_id, 'created', :total_groups,
                :created_at, :expires_at
            )
        """), {
            "operation_id": operation_id,
            "actor_user_id": int(actor_user_id),
            "total_groups": len(groups),
            "created_at": now,
            "expires_at": expires_at,
        })
        for group in groups:
            conn.execute(text("""
                INSERT INTO adeus_recovery_items (
                    operation_id, chat_id, title, prepare_status,
                    created_at, updated_at
                ) VALUES (
                    :operation_id, :chat_id, :title, 'pending',
                    :created_at, :updated_at
                )
            """), {
                "operation_id": operation_id,
                "chat_id": int(group["chat_id"]),
                "title": group.get("title") or "grupo gerenciado",
                "created_at": now,
                "updated_at": now,
            })
    log_audit_event(
        category="adeus",
        action="operation_created",
        status="success",
        actor_user_id=int(actor_user_id),
        payload={"operation_id": operation_id, "total_groups": len(groups)},
    )
    return operation_id


def get_operation(operation_id: str) -> dict[str, Any] | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT id, operation_id, actor_user_id, status, total_groups,
                   prepared_count, failed_prepare_count, left_count,
                   failed_leave_count, created_at, confirmed_at, executed_at, expires_at
              FROM adeus_recovery_operations
             WHERE operation_id=:operation_id
             LIMIT 1
        """), {"operation_id": operation_id}).mappings().first()
    return dict(row) if row else None


def list_recovery_operations(limit: int = 10) -> list[dict[str, Any]]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, operation_id, actor_user_id, status, total_groups,
                   prepared_count, failed_prepare_count, left_count,
                   failed_leave_count, created_at, confirmed_at, executed_at, expires_at
              FROM adeus_recovery_operations
             ORDER BY id DESC
             LIMIT :limit
        """), {"limit": max(1, min(int(limit), 50))}).mappings().all()
    return [dict(row) for row in rows]


def list_recovery_items(operation_id: str | None = None, *, pending_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    ensure_tables()
    clauses = []
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if operation_id:
        clauses.append("operation_id=:operation_id")
        params["operation_id"] = operation_id
    if pending_only:
        clauses.append("COALESCE(rejoin_status, '') NOT IN ('rejoined')")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with engine.begin() as conn:
        rows = conn.execute(text(f"""
            SELECT id, operation_id, chat_id, title, bot_status_before,
                   can_invite_users_before, invite_link, invite_expires_at,
                   prepare_status, leave_status, rejoin_status, last_error,
                   created_at, updated_at
              FROM adeus_recovery_items
              {where}
             ORDER BY id DESC
             LIMIT :limit
        """), params).mappings().all()
    return [dict(row) for row in rows]


def _update_operation_counts(operation_id: str) -> None:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT prepare_status, leave_status
              FROM adeus_recovery_items
             WHERE operation_id=:operation_id
        """), {"operation_id": operation_id}).mappings().all()
        prepared = sum(1 for r in rows if r.get("prepare_status") == "prepared")
        failed_prepare = sum(1 for r in rows if str(r.get("prepare_status") or "").startswith("error"))
        left = sum(1 for r in rows if r.get("leave_status") == "left")
        failed_leave = sum(1 for r in rows if str(r.get("leave_status") or "").startswith("error"))
        conn.execute(text("""
            UPDATE adeus_recovery_operations
               SET prepared_count=:prepared,
                   failed_prepare_count=:failed_prepare,
                   left_count=:left_count,
                   failed_leave_count=:failed_leave
             WHERE operation_id=:operation_id
        """), {
            "operation_id": operation_id,
            "prepared": prepared,
            "failed_prepare": failed_prepare,
            "left_count": left,
            "failed_leave": failed_leave,
        })


async def prepare_recovery_links(bot: Bot, operation_id: str) -> dict[str, Any]:
    ensure_tables()
    op = get_operation(operation_id)
    if not op:
        raise ValueError("operação de recuperação não encontrada")
    items = list_recovery_items(operation_id, limit=10000)
    now = utcnow()
    expire_at = now + timedelta(days=7)
    for item in items:
        chat_id = int(item["chat_id"])
        title = str(item.get("title") or "grupo gerenciado")
        status = "error_prepare"
        invite_link = None
        err = None
        rights = await get_bot_rights(bot, chat_id, force_refresh=True)
        try:
            if rights.error:
                raise RuntimeError(rights.error)
            if not rights.is_admin or not rights.can_invite_users:
                raise RuntimeError("bot sem permissão can_invite_users para criar link de recuperação")
            link = await bot.create_chat_invite_link(
                chat_id=chat_id,
                name="TR3 recovery",
                expire_date=expire_at,
                creates_join_request=False,
            )
            invite_link = getattr(link, "invite_link", None)
            if not invite_link:
                raise RuntimeError("Telegram não retornou invite_link")
            status = "prepared"
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"[:500]
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE adeus_recovery_items
                   SET bot_status_before=:bot_status_before,
                       can_invite_users_before=:can_invite_users_before,
                       invite_link=:invite_link,
                       invite_expires_at=:invite_expires_at,
                       prepare_status=:prepare_status,
                       last_error=:last_error,
                       updated_at=:updated_at
                 WHERE operation_id=:operation_id AND chat_id=:chat_id
            """), {
                "operation_id": operation_id,
                "chat_id": chat_id,
                "bot_status_before": rights.status,
                "can_invite_users_before": 1 if rights.can_invite_users else 0,
                "invite_link": invite_link,
                "invite_expires_at": expire_at if invite_link else None,
                "prepare_status": status,
                "last_error": err,
                "updated_at": utcnow(),
            })
        log_audit_event(
            category="adeus",
            action="recovery_link_created" if status == "prepared" else "recovery_link_failed",
            status="success" if status == "prepared" else "error",
            actor_user_id=int(op["actor_user_id"]),
            chat_id=chat_id,
            reason=err,
            payload={"operation_id": operation_id, "title": title},
        )
    with engine.begin() as conn:
        conn.execute(text("UPDATE adeus_recovery_operations SET status='prepared' WHERE operation_id=:operation_id"), {"operation_id": operation_id})
    _update_operation_counts(operation_id)
    return get_operation(operation_id) or {}


def confirm_operation(operation_id: str, *, actor_user_id: int) -> None:
    ensure_tables()
    _update_operation_counts(operation_id)
    op = get_operation(operation_id)
    if not op:
        raise ValueError("operação de recuperação não encontrada")
    if str(op.get("status")) != "prepared":
        raise ValueError("prepare a recuperação antes de confirmar")
    if int(op.get("prepared_count") or 0) <= 0:
        raise ValueError("nenhum grupo possui link de recuperação preparado")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE adeus_recovery_operations
               SET status='confirmed', confirmed_at=:confirmed_at
             WHERE operation_id=:operation_id
        """), {"operation_id": operation_id, "confirmed_at": utcnow()})
    log_audit_event(category="adeus", action="operation_confirmed", status="success", actor_user_id=int(actor_user_id), payload={"operation_id": operation_id})


def cancel_operation(operation_id: str, *, actor_user_id: int) -> None:
    ensure_tables()
    op = get_operation(operation_id)
    if not op:
        raise ValueError("operação de recuperação não encontrada")
    if str(op.get("status")) == "executed":
        raise ValueError("operação já executada não pode ser cancelada")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE adeus_recovery_operations
               SET status='cancelled'
             WHERE operation_id=:operation_id
        """), {"operation_id": operation_id})
    log_audit_event(category="adeus", action="operation_cancelled", status="success", actor_user_id=int(actor_user_id), payload={"operation_id": operation_id})


async def execute_leave_operation(bot: Bot, operation_id: str, *, actor_user_id: int) -> dict[str, Any]:
    ensure_tables()
    op = get_operation(operation_id)
    if not op:
        raise ValueError("operação de recuperação não encontrada")
    if str(op.get("status")) != "confirmed":
        raise ValueError("operação precisa estar confirmada antes da saída")
    items = list_recovery_items(operation_id, limit=10000)
    for item in items:
        chat_id = int(item["chat_id"])
        leave_status = "error_leave"
        err = None
        if item.get("prepare_status") != "prepared" or not item.get("invite_link"):
            leave_status = "skipped_no_recovery"
            err = "sem link de recuperação preparado; saída bloqueada por segurança"
        else:
            try:
                await bot.leave_chat(chat_id)
                leave_status = "left"
                update_group_status(chat_id=chat_id, bot_status="left_pending_rejoin", last_error="adeus executed; pending manual rejoin")
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                err = f"{type(exc).__name__}: {exc}"[:500]
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"[:500]
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE adeus_recovery_items
                   SET leave_status=:leave_status,
                       rejoin_status=CASE WHEN :leave_status='left' THEN 'pending' ELSE rejoin_status END,
                       last_error=COALESCE(:last_error, last_error),
                       updated_at=:updated_at
                 WHERE operation_id=:operation_id AND chat_id=:chat_id
            """), {
                "operation_id": operation_id,
                "chat_id": chat_id,
                "leave_status": leave_status,
                "last_error": err,
                "updated_at": utcnow(),
            })
        log_audit_event(
            category="adeus",
            action="leave_chat" if leave_status != "skipped_no_recovery" else "leave_skipped_no_recovery",
            status="success" if leave_status == "left" else "blocked" if leave_status == "skipped_no_recovery" else "error",
            actor_user_id=int(actor_user_id),
            chat_id=chat_id,
            reason=err,
            payload={"operation_id": operation_id},
        )
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE adeus_recovery_operations
               SET status='executed', executed_at=:executed_at
             WHERE operation_id=:operation_id
        """), {"operation_id": operation_id, "executed_at": utcnow()})
    _update_operation_counts(operation_id)
    return get_operation(operation_id) or {}


def mark_rejoin_detected(chat_id: int, *, title: str | None = None, status: str | None = None) -> int:
    ensure_tables()
    with engine.begin() as conn:
        res = conn.execute(text("""
            UPDATE adeus_recovery_items
               SET rejoin_status='rejoined',
                   last_error=NULL,
                   title=COALESCE(:title, title),
                   updated_at=:updated_at
             WHERE chat_id=:chat_id
               AND COALESCE(rejoin_status, '') NOT IN ('rejoined')
        """), {"chat_id": int(chat_id), "title": title, "updated_at": utcnow()})
    if status:
        update_group_status(chat_id=int(chat_id), bot_status=status, last_error=None)
    return int(res.rowcount or 0)
