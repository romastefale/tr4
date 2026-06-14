"""Owner daily summaries for Equalizador governante limits."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.governante_scope import (
    daily_limit_summary_text,
    mark_daily_limit_summary_dispatch_result,
    reserve_daily_limit_summary_dispatch,
)

logger = logging.getLogger(__name__)


def _sao_paulo_tz():
    try:
        return ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_now(now: datetime | None = None) -> datetime:
    tz = _sao_paulo_tz()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


async def send_daily_limit_summary_to_owners(
    bot: Bot,
    *,
    db_engine: Engine = default_engine,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Send one consolidated governante limit summary per local day.

    Normal scheduler mode sends after 23:55 America/Sao_Paulo and persists a
    dispatch reservation, avoiding duplicate DMs after restarts. ``force=True``
    bypasses the time window but still respects the once-per-date reservation.
    """
    local = _local_now(now)
    summary_date = local.date().isoformat()
    if not force and (local.hour, local.minute) < (23, 55):
        return {"ok": True, "skipped": "fora_janela", "date": summary_date}
    if not reserve_daily_limit_summary_dispatch(summary_date=summary_date, db_engine=db_engine):
        return {"ok": True, "skipped": "ja_enviado", "date": summary_date}

    text_value = daily_limit_summary_text(alias_secret=settings.equalizador_alias_secret(), db_engine=db_engine)
    owners = sorted(int(uid) for uid in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET if int(uid) > 0)
    sent = 0
    failed = 0
    for owner_id in owners:
        try:
            await bot.send_message(chat_id=owner_id, text=text_value[:3900], disable_web_page_preview=True)
            sent += 1
        except Exception:
            failed += 1
            logger.debug("DAILY_LIMIT_SUMMARY_DM_FAILED owner=%s", owner_id, exc_info=True)
    mark_daily_limit_summary_dispatch_result(summary_date=summary_date, sent_count=sent, failed_count=failed, db_engine=db_engine)
    return {"ok": True, "date": summary_date, "sent": sent, "failed": failed}
