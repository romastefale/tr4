from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from sqlalchemy import text

from app.config.settings import BASE_URL, SECURITY_MONITOR_ENABLED, SECURITY_MONITOR_INTERVAL_SECONDS, SECURITY_MONITOR_MAX_GROUPS
from app.db.database import engine
from app.security.audit import log_audit_event
from app.security.alerts import send_security_alert
from app.security.bot_rights import get_bot_rights
from app.security.managed_groups import list_managed_groups
from app.security.panic import record_security_signal, security_status, set_security_mode
from app.security.task_registry import spawn_task

logger = logging.getLogger(__name__)

_MONITOR_TASK_NAME = "security.monitor"
_monitor_running = False


def _audit_check(action: str, status: str, *, reason: str | None = None, payload: dict[str, Any] | None = None) -> None:
    try:
        log_audit_event(category="security_check", action=action, status=status, reason=reason, payload=payload or {})
    except Exception:
        logger.debug("SECURITY_CHECK_AUDIT_FAILED | action=%s", action, exc_info=True)


async def _check_db() -> bool:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        _audit_check("db", "success")
        return True
    except Exception as exc:
        logger.exception("SECURITY_DB_CHECK_FAILED")
        _audit_check("db", "error", reason=str(exc)[:300])
        set_security_mode("restricted", reason="database health check failed")
        return False


async def _check_webhook(bot: Bot) -> bool:
    try:
        info = await bot.get_webhook_info()
        current_url = str(getattr(info, "url", "") or "")
        expected_url = f"{BASE_URL}/webhook"
        pending_count = int(getattr(info, "pending_update_count", 0) or 0)
        last_error = getattr(info, "last_error_message", None)
        payload = {"url": current_url, "expected_url": expected_url, "pending_update_count": pending_count}
        if last_error:
            payload["last_error_message"] = str(last_error)[:300]
        if current_url and current_url != expected_url:
            _audit_check("webhook", "error", reason="webhook URL mismatch", payload=payload)
            await send_security_alert(
                bot,
                title="webhook_url_mismatch",
                detail="Webhook URL atual diverge do BASE_URL configurado.",
                severity="restricted",
                payload=payload,
                dedupe_key="webhook_url_mismatch",
            )
            set_security_mode("restricted", reason="webhook URL mismatch")
            return False
        if last_error:
            record_security_signal("webhook.last_error", threshold=3, reason=str(last_error)[:200])
        _audit_check("webhook", "success", payload=payload)
        return True
    except Exception as exc:
        logger.exception("SECURITY_WEBHOOK_CHECK_FAILED")
        _audit_check("webhook", "error", reason=str(exc)[:300])
        record_security_signal("webhook.check_failed", threshold=3, reason=type(exc).__name__)
        await send_security_alert(
            bot,
            title="webhook_check_failed",
            detail=f"Falha ao consultar getWebhookInfo: {type(exc).__name__}",
            severity="alert",
            payload={"error": str(exc)[:300]},
            dedupe_key="webhook_check_failed",
        )
        return False


async def _check_managed_groups(bot: Bot) -> None:
    try:
        groups = list_managed_groups(limit=SECURITY_MONITOR_MAX_GROUPS)
    except Exception as exc:
        logger.exception("SECURITY_MANAGED_GROUP_LIST_FAILED")
        _audit_check("managed_groups", "error", reason=str(exc)[:300])
        return
    checked = 0
    admin_lost = 0
    for row in groups:
        if not row.get("enabled"):
            continue
        chat_id = int(row["chat_id"])
        rights = await get_bot_rights(bot, chat_id, force_refresh=True)
        checked += 1
        if not rights.is_admin:
            admin_lost += 1
            record_security_signal("managed_group.admin_lost", threshold=1, reason=str(chat_id))
            payload = {"chat_id": chat_id, "status": rights.status}
            _audit_check(
                "managed_group_rights",
                "error",
                reason=rights.musical_only_reason or "bot is not admin",
                payload=payload,
            )
            await send_security_alert(
                bot,
                title="managed_group_admin_lost",
                detail=rights.musical_only_reason or "Bot não é admin em grupo gerenciado.",
                severity="restricted",
                payload=payload,
                dedupe_key=f"managed_group_admin_lost:{chat_id}",
            )
        else:
            _audit_check(
                "managed_group_rights",
                "success",
                payload={
                    "chat_id": chat_id,
                    "status": rights.status,
                    "can_delete_messages": rights.can_delete_messages,
                    "can_restrict_members": rights.can_restrict_members,
                },
            )
    logger.info("SECURITY_MANAGED_GROUPS_CHECKED | checked=%s | admin_lost=%s", checked, admin_lost)


async def run_once(bot: Bot) -> dict[str, object]:
    db_ok = await _check_db()
    webhook_ok = await _check_webhook(bot)
    await _check_managed_groups(bot)
    return {"db_ok": db_ok, "webhook_ok": webhook_ok, "security": security_status()}


async def _monitor_loop(bot: Bot) -> None:
    global _monitor_running
    _monitor_running = True
    logger.warning("SECURITY_MONITOR_STARTED | interval=%ss", SECURITY_MONITOR_INTERVAL_SECONDS)
    try:
        while True:
            await run_once(bot)
            await asyncio.sleep(max(30, SECURITY_MONITOR_INTERVAL_SECONDS))
    except asyncio.CancelledError:
        logger.warning("SECURITY_MONITOR_CANCELLED")
        raise
    finally:
        _monitor_running = False


def start_security_monitor(bot: Bot) -> None:
    if not SECURITY_MONITOR_ENABLED:
        logger.warning("SECURITY_MONITOR_DISABLED")
        return
    if _monitor_running:
        return
    spawn_task(_monitor_loop(bot), name=_MONITOR_TASK_NAME)


def is_security_monitor_running() -> bool:
    return _monitor_running
