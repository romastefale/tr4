from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot

from app.config.settings import AUDIT_LOG_CHAT_ID, SECURITY_ALERT_CHAT_ID, SECURITY_ALERTS_ENABLED
from app.security.audit import log_audit_event

logger = logging.getLogger(__name__)


def _escape(value: object) -> str:
    return html.escape(str(value or ""))


def _format_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    lines: list[str] = []
    for key, value in list(payload.items())[:10]:
        text = str(value)
        if len(text) > 240:
            text = text[:237] + "..."
        lines.append(f"• <b>{_escape(key)}</b>: <code>{_escape(text)}</code>")
    return "\n" + "\n".join(lines) if lines else ""


async def send_security_alert(
    bot: Bot,
    *,
    title: str,
    detail: str,
    severity: str = "alert",
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Send a best-effort security alert to Owner/audit chat.

    Alerts must never break the main moderation pipeline. Failures are logged
    and the corresponding audit event remains local in SQLite.
    """
    try:
        log_audit_event(
            category="security_alert",
            action=dedupe_key or title,
            status=severity,
            reason=detail,
            payload=payload or {},
        )
    except Exception:
        logger.debug("SECURITY_ALERT_AUDIT_FAILED", exc_info=True)

    if not SECURITY_ALERTS_ENABLED:
        return

    targets = []
    for chat_id in (SECURITY_ALERT_CHAT_ID, AUDIT_LOG_CHAT_ID):
        if chat_id and chat_id not in targets:
            targets.append(chat_id)
    if not targets:
        return

    body = (
        f"Tigrão — alerta de segurança\n\n"
        f"Severidade: <b>{_escape(severity)}</b>\n"
        f"Evento: <b>{_escape(title)}</b>\n"
        f"Detalhe: {_escape(detail)}"
        f"{_format_payload(payload)}"
    )
    for chat_id in targets:
        try:
            await bot.send_message(chat_id=chat_id, text=body, parse_mode="HTML")
        except Exception:
            logger.exception("SECURITY_ALERT_SEND_FAILED | chat_id=%s | title=%s", chat_id, title)
