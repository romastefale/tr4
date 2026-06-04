from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from app.config.settings import (
    RADIO_SCHEDULER_ENABLED,
    RADIO_SCHEDULER_INTERVAL_SECONDS,
    RADIO_SCHEDULER_MAX_DUE_PER_TICK,
    ROOT_USER_ID,
    OPERATIONAL_LOCK_TTL_SECONDS,
)
from app.db.database import engine
from app.security.audit import log_audit_event
from app.security.bot_rights import check_group_capability
from app.security.managed_groups import list_managed_groups
from app.security.session_store import acquire_operational_lock, release_operational_lock
from app.security.critical_operations import begin_critical_operation, finish_critical_operation
from app.security.radio_templates import (
    DEFAULT_DEDUPE_WINDOW_SECONDS,
    find_recent_duplicate,
    get_template,
    message_hash,
    record_post_history,
)
from app.security.task_registry import spawn_task

logger = logging.getLogger(__name__)

_SCHEDULER_STARTED = False


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
                CREATE TABLE IF NOT EXISTS radio_group_policies (
                    chat_id INTEGER PRIMARY KEY,
                    quiet_from TEXT,
                    quiet_to TEXT,
                    utc_offset_minutes INTEGER NOT NULL DEFAULT 0,
                    allow_owner_override INTEGER NOT NULL DEFAULT 1,
                    updated_by_user_id INTEGER,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radio_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    interval_seconds INTEGER NOT NULL,
                    pin INTEGER NOT NULL DEFAULT 0,
                    created_by_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_sent_at DATETIME,
                    next_due_at DATETIME NOT NULL,
                    last_status TEXT,
                    last_error TEXT
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_radio_schedules_due ON radio_schedules(enabled, next_due_at);"))


def parse_hhmm(value: str) -> time:
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("use HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("hora fora do intervalo")
    return time(hour=hour, minute=minute)


def parse_utc_offset_minutes(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    sign = 1
    if raw[0] == "-":
        sign = -1
        raw = raw[1:]
    elif raw[0] == "+":
        raw = raw[1:]
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("offset deve ser +HH:MM ou -HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("offset fora do intervalo")
    return sign * (hour * 60 + minute)


def format_utc_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    value = abs(int(minutes))
    return f"{sign}{value // 60:02d}:{value % 60:02d}"


def set_group_policy(
    *,
    chat_id: int,
    quiet_from: str | None,
    quiet_to: str | None,
    utc_offset_minutes: int = 0,
    allow_owner_override: bool = True,
    updated_by_user_id: int | None = None,
) -> None:
    ensure_tables()
    if quiet_from:
        parse_hhmm(quiet_from)
    if quiet_to:
        parse_hhmm(quiet_to)
    if bool(quiet_from) != bool(quiet_to):
        raise ValueError("quiet_from e quiet_to devem ser definidos juntos")
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO radio_group_policies (
                    chat_id, quiet_from, quiet_to, utc_offset_minutes,
                    allow_owner_override, updated_by_user_id, updated_at
                )
                VALUES (
                    :chat_id, :quiet_from, :quiet_to, :utc_offset_minutes,
                    :allow_owner_override, :updated_by_user_id, :updated_at
                )
                ON CONFLICT(chat_id) DO UPDATE SET
                    quiet_from = excluded.quiet_from,
                    quiet_to = excluded.quiet_to,
                    utc_offset_minutes = excluded.utc_offset_minutes,
                    allow_owner_override = excluded.allow_owner_override,
                    updated_by_user_id = excluded.updated_by_user_id,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "chat_id": int(chat_id),
                "quiet_from": quiet_from,
                "quiet_to": quiet_to,
                "utc_offset_minutes": int(utc_offset_minutes),
                "allow_owner_override": 1 if allow_owner_override else 0,
                "updated_by_user_id": int(updated_by_user_id) if updated_by_user_id else None,
                "updated_at": _serialize_dt(now),
            },
        )


def get_group_policy(chat_id: int) -> dict | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM radio_group_policies WHERE chat_id = :chat_id"),
            {"chat_id": int(chat_id)},
        ).fetchone()
    return _row_to_dict(row)


def is_quiet_now(chat_id: int, *, now: datetime | None = None) -> bool:
    policy = get_group_policy(chat_id)
    if not policy or not policy.get("quiet_from") or not policy.get("quiet_to"):
        return False
    current = now or utcnow()
    offset = timedelta(minutes=int(policy.get("utc_offset_minutes") or 0))
    local = (current + offset).time()
    start = parse_hhmm(str(policy["quiet_from"]))
    end = parse_hhmm(str(policy["quiet_to"]))
    if start < end:
        return start <= local < end
    return local >= start or local < end


def create_schedule(
    *,
    template_id: int,
    chat_id: int,
    interval_seconds: int,
    created_by_user_id: int,
    pin: bool = False,
    start_after_seconds: int | None = None,
) -> int:
    ensure_tables()
    if get_template(template_id) is None:
        raise ValueError("template não encontrado")
    if interval_seconds < 60:
        raise ValueError("intervalo mínimo é 60 segundos")
    now = utcnow()
    next_due = now + timedelta(seconds=int(start_after_seconds if start_after_seconds is not None else interval_seconds))
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO radio_schedules (
                    template_id, chat_id, enabled, interval_seconds, pin,
                    created_by_user_id, created_at, updated_at, next_due_at
                )
                VALUES (
                    :template_id, :chat_id, 1, :interval_seconds, :pin,
                    :created_by_user_id, :created_at, :updated_at, :next_due_at
                )
                """
            ),
            {
                "template_id": int(template_id),
                "chat_id": int(chat_id),
                "interval_seconds": int(interval_seconds),
                "pin": 1 if pin else 0,
                "created_by_user_id": int(created_by_user_id),
                "created_at": _serialize_dt(now),
                "updated_at": _serialize_dt(now),
                "next_due_at": _serialize_dt(next_due),
            },
        )
        return int(result.lastrowid)


def list_schedules(*, chat_id: int | None = None, limit: int = 20, offset: int = 0) -> list[dict]:
    ensure_tables()
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with engine.begin() as conn:
        if chat_id is None:
            rows = conn.execute(
                text("SELECT * FROM radio_schedules ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {"limit": safe_limit, "offset": safe_offset},
            ).fetchall()
        else:
            rows = conn.execute(
                text("SELECT * FROM radio_schedules WHERE chat_id=:chat_id ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {"chat_id": int(chat_id), "limit": safe_limit, "offset": safe_offset},
            ).fetchall()
    return [dict(row._mapping) for row in rows]


def set_schedule_enabled(schedule_id: int, enabled: bool) -> bool:
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE radio_schedules
                   SET enabled=:enabled, updated_at=:updated_at
                 WHERE id=:id
                """
            ),
            {"id": int(schedule_id), "enabled": 1 if enabled else 0, "updated_at": _serialize_dt(now)},
        )
    return bool(result.rowcount)


def delete_schedule(schedule_id: int) -> bool:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM radio_schedules WHERE id=:id"), {"id": int(schedule_id)})
    return bool(result.rowcount)


def due_schedules(*, now: datetime | None = None, limit: int | None = None) -> list[dict]:
    ensure_tables()
    current = now or utcnow()
    safe_limit = max(1, min(int(limit or RADIO_SCHEDULER_MAX_DUE_PER_TICK), 100))
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT *
                  FROM radio_schedules
                 WHERE enabled = 1
                   AND next_due_at <= :now
                 ORDER BY next_due_at ASC
                 LIMIT :limit
                """
            ),
            {"now": _serialize_dt(current), "limit": safe_limit},
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def _update_schedule_after_attempt(schedule_id: int, *, status: str, error: str | None = None, sent: bool = False) -> None:
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT interval_seconds FROM radio_schedules WHERE id=:id"),
            {"id": int(schedule_id)},
        ).fetchone()
        interval = int(row[0]) if row else 3600
        conn.execute(
            text(
                """
                UPDATE radio_schedules
                   SET updated_at=:updated_at,
                       last_sent_at=CASE WHEN :sent = 1 THEN :updated_at ELSE last_sent_at END,
                       next_due_at=:next_due_at,
                       last_status=:last_status,
                       last_error=:last_error
                 WHERE id=:id
                """
            ),
            {
                "id": int(schedule_id),
                "updated_at": _serialize_dt(now),
                "next_due_at": _serialize_dt(now + timedelta(seconds=max(60, interval))),
                "last_status": status,
                "last_error": (error or "")[:1000] if error else None,
                "sent": 1 if sent else 0,
            },
        )


async def _send_template(bot, *, template: dict, chat_id: int, pin: bool) -> int:
    sent = await bot.send_message(chat_id=int(chat_id), text=str(template.get("body") or ""))
    if pin:
        allowed, reason, _rights = await check_group_capability(bot, int(chat_id), "pin")
        if not allowed:
            raise RuntimeError(f"bot sem permissão para fixar: {reason}")
        await bot.pin_chat_message(chat_id=int(chat_id), message_id=sent.message_id, disable_notification=True)
    return int(sent.message_id)


async def _run_due_schedules_unlocked(bot, *, max_count: int | None = None) -> dict[str, int]:
    ensure_tables()
    result = {"sent": 0, "skipped": 0, "error": 0}
    for schedule in due_schedules(limit=max_count):
        schedule_id = int(schedule["id"])
        chat_id = int(schedule["chat_id"])
        template_id = int(schedule["template_id"])
        pin = bool(int(schedule.get("pin") or 0))
        template = get_template(template_id)
        if not template:
            _update_schedule_after_attempt(schedule_id, status="error", error="template_not_found")
            result["error"] += 1
            continue

        content_hash = message_hash(str(template.get("body") or ""))
        if is_quiet_now(chat_id):
            record_post_history(
                actor_user_id=int(schedule.get("created_by_user_id") or ROOT_USER_ID or 0),
                chat_id=chat_id,
                kind="scheduled_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="skipped",
                reason="quiet_hours",
            )
            _update_schedule_after_attempt(schedule_id, status="skipped", error="quiet_hours")
            result["skipped"] += 1
            continue

        duplicate = find_recent_duplicate(
            chat_id=chat_id,
            message_hash_value=content_hash,
            window_seconds=DEFAULT_DEDUPE_WINDOW_SECONDS,
        )
        if duplicate:
            record_post_history(
                actor_user_id=int(schedule.get("created_by_user_id") or ROOT_USER_ID or 0),
                chat_id=chat_id,
                kind="scheduled_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="blocked",
                reason="duplicate_recent",
            )
            _update_schedule_after_attempt(schedule_id, status="blocked", error="duplicate_recent")
            result["skipped"] += 1
            continue

        try:
            message_id = await _send_template(bot, template=template, chat_id=chat_id, pin=pin)
        except Exception as exc:
            record_post_history(
                actor_user_id=int(schedule.get("created_by_user_id") or ROOT_USER_ID or 0),
                chat_id=chat_id,
                kind="scheduled_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="error",
                reason=type(exc).__name__,
            )
            _update_schedule_after_attempt(schedule_id, status="error", error=f"{type(exc).__name__}: {exc}")
            logger.exception("RADIO_SCHEDULE_SEND_FAILED schedule=%s chat=%s", schedule_id, chat_id)
            result["error"] += 1
            continue

        record_post_history(
            actor_user_id=int(schedule.get("created_by_user_id") or ROOT_USER_ID or 0),
            chat_id=chat_id,
            kind="scheduled_text",
            pin=pin,
            template_id=template_id,
            message_hash_value=content_hash,
            telegram_message_id=message_id,
            status="success",
        )
        log_audit_event(
            category="radio",
            action="schedule_send",
            status="success",
            actor_user_id=int(schedule.get("created_by_user_id") or ROOT_USER_ID or 0),
            chat_id=chat_id,
            target_message_id=message_id,
            payload={"schedule_id": schedule_id, "template_id": template_id, "pin": pin},
        )
        _update_schedule_after_attempt(schedule_id, status="success", sent=True)
        result["sent"] += 1
    return result


async def run_due_schedules(bot, *, max_count: int | None = None) -> dict[str, int]:
    lock = acquire_operational_lock(
        "radio_scheduler",
        ttl_seconds=OPERATIONAL_LOCK_TTL_SECONDS,
        metadata={"max_count": max_count},
    )
    if not lock.acquired:
        return {"sent": 0, "skipped": 0, "error": 0, "locked": 1}
    try:
        return await _run_due_schedules_unlocked(bot, max_count=max_count)
    finally:
        release_operational_lock("radio_scheduler", owner=lock.owner)


async def _broadcast_template_to_managed_groups_unlocked(
    bot,
    *,
    template_id: int,
    actor_user_id: int,
    pin: bool = False,
    chat_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    ensure_tables()
    template = get_template(template_id)
    if not template:
        raise ValueError("template não encontrado")

    allowed_chat_ids = {int(chat_id) for chat_id in chat_ids} if chat_ids is not None else None
    groups = [
        g for g in list_managed_groups(limit=500)
        if int(g.get("enabled") or 0) == 1
        and (allowed_chat_ids is None or int(g["chat_id"]) in allowed_chat_ids)
    ]
    content_hash = message_hash(str(template.get("body") or ""))
    results: list[dict[str, Any]] = []

    for group in groups:
        chat_id = int(group["chat_id"])
        row: dict[str, Any] = {"chat_id": chat_id, "status": "pending"}
        if is_quiet_now(chat_id):
            row.update(status="skipped", reason="quiet_hours")
            record_post_history(
                actor_user_id=actor_user_id,
                chat_id=chat_id,
                kind="broadcast_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="skipped",
                reason="quiet_hours",
            )
            results.append(row)
            continue
        duplicate = find_recent_duplicate(chat_id=chat_id, message_hash_value=content_hash)
        if duplicate:
            row.update(status="blocked", reason="duplicate_recent")
            record_post_history(
                actor_user_id=actor_user_id,
                chat_id=chat_id,
                kind="broadcast_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="blocked",
                reason="duplicate_recent",
            )
            results.append(row)
            continue
        try:
            message_id = await _send_template(bot, template=template, chat_id=chat_id, pin=pin)
        except Exception as exc:
            row.update(status="error", reason=type(exc).__name__)
            record_post_history(
                actor_user_id=actor_user_id,
                chat_id=chat_id,
                kind="broadcast_text",
                pin=pin,
                template_id=template_id,
                message_hash_value=content_hash,
                status="error",
                reason=type(exc).__name__,
            )
            results.append(row)
            continue
        row.update(status="success", message_id=message_id)
        record_post_history(
            actor_user_id=actor_user_id,
            chat_id=chat_id,
            kind="broadcast_text",
            pin=pin,
            template_id=template_id,
            message_hash_value=content_hash,
            telegram_message_id=message_id,
            status="success",
        )
        results.append(row)

    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] in {"skipped", "blocked"}),
        "error": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
    log_audit_event(
        category="radio",
        action="broadcast_managed_groups",
        status="success",
        actor_user_id=actor_user_id,
        payload={"template_id": template_id, "pin": pin, **{k: summary[k] for k in ("total", "success", "skipped", "error")}},
    )
    return summary


async def broadcast_template_to_managed_groups(
    bot,
    *,
    template_id: int,
    actor_user_id: int,
    pin: bool = False,
    chat_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    intent = {
        "template_id": int(template_id),
        "actor_user_id": int(actor_user_id),
        "pin": bool(pin),
        "chat_ids": sorted({int(chat_id) for chat_id in chat_ids}) if chat_ids is not None else None,
    }
    operation_id = begin_critical_operation(
        category="radio",
        action="broadcast_managed_groups",
        operation_key=f"radio_broadcast:{template_id}:{actor_user_id}",
        actor_user_id=actor_user_id,
        lock_name="radio_broadcast",
        intent=intent,
    )
    lock = acquire_operational_lock(
        "radio_broadcast",
        ttl_seconds=OPERATIONAL_LOCK_TTL_SECONDS,
        metadata={"template_id": template_id, "actor_user_id": actor_user_id, "pin": pin, "operation_id": operation_id},
    )
    if not lock.acquired:
        summary = {"total": 0, "success": 0, "skipped": 0, "error": 0, "locked": 1, "results": [], "operation_id": operation_id}
        finish_critical_operation(
            operation_id,
            status="blocked",
            result=summary,
            reason="operational_lock_busy",
        )
        log_audit_event(
            category="radio",
            action="broadcast_lock_busy",
            status="blocked",
            actor_user_id=actor_user_id,
            payload={"template_id": template_id, "lock_owner": lock.owner, "expires_at": lock.expires_at, "operation_id": operation_id},
        )
        return summary
    try:
        result = await _broadcast_template_to_managed_groups_unlocked(
            bot,
            template_id=template_id,
            actor_user_id=actor_user_id,
            pin=pin,
            chat_ids=chat_ids,
        )
        result["operation_id"] = operation_id
        finish_critical_operation(
            operation_id,
            status="success" if int(result.get("error", 0)) == 0 else "partial",
            result={k: result.get(k) for k in ("total", "success", "skipped", "error", "locked")},
        )
        return result
    except Exception as exc:
        finish_critical_operation(operation_id, status="error", result={"error": str(exc)[:1000]}, reason=type(exc).__name__)
        raise
    finally:
        release_operational_lock("radio_broadcast", owner=lock.owner)


async def _scheduler_loop(bot) -> None:
    while True:
        try:
            await run_due_schedules(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RADIO_SCHEDULER_TICK_FAILED")
        await asyncio.sleep(max(30, int(RADIO_SCHEDULER_INTERVAL_SECONDS)))


def start_radio_scheduler(bot) -> bool:
    global _SCHEDULER_STARTED
    if _SCHEDULER_STARTED:
        return False
    if not RADIO_SCHEDULER_ENABLED:
        return False
    _SCHEDULER_STARTED = True
    spawn_task(_scheduler_loop(bot), name="radio_scheduler", context={"interval": RADIO_SCHEDULER_INTERVAL_SECONDS})
    return True


def is_radio_scheduler_started() -> bool:
    return _SCHEDULER_STARTED
