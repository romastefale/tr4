from __future__ import annotations

import html
import logging
from typing import Any

from app.config.settings import LYRICS_ARCHIVE_ENABLED, LYRICS_CACHE_CHANNEL_ID
from app.services.lyrics_cache import lyrics_snippet_cache_service

logger = logging.getLogger(__name__)


def _caption_with_open_quote(base_caption: str, lyric_snippet: str | None, *, limit: int = 1024) -> str | None:
    """Monta a mesma legenda curta usada pelo /tly, limitada ao caption do Telegram."""
    raw = (lyric_snippet or "").strip()
    if not raw:
        return None
    candidate_raw = raw
    while candidate_raw:
        display = candidate_raw if candidate_raw == raw else candidate_raw.rstrip("…").rstrip() + "…"
        candidate = f"{base_caption}\n<blockquote>{html.escape(display)}</blockquote>"
        if len(candidate) <= limit:
            return candidate
        candidate_raw = candidate_raw[:-120].rstrip()
    return None


async def archive_tly_snippet(
    bot: Any,
    *,
    artist: str,
    title: str,
    base_caption: str,
    lyric_snippet: str | None,
    cover: str | bytes | None = None,
) -> tuple[int, int] | None:
    """Arquiva o post técnico de letra no canal e indexa no banco.

    O banco continua sendo a fonte de verdade. O canal técnico é apenas
    armazenamento/auditoria por chat_id + message_id. Falhas aqui nunca devem
    quebrar o envio ao usuário.
    """
    if not (LYRICS_ARCHIVE_ENABLED and LYRICS_CACHE_CHANNEL_ID):
        return None
    if not bot or not artist or not title:
        return None
    caption = _caption_with_open_quote(base_caption, lyric_snippet)
    if not caption:
        return None

    try:
        existing = await lyrics_snippet_cache_service.get_archive_ref(artist, title)
        if existing:
            return existing
    except Exception:
        logger.debug("LYRICS_ARCHIVE_REF_CHECK_FAILED artist=%s title=%s", artist, title, exc_info=True)

    sent = None
    if cover:
        try:
            photo_payload = cover
            if isinstance(cover, bytes):
                from aiogram.types import BufferedInputFile

                photo_payload = BufferedInputFile(cover, filename="tly-lyrics.jpg")
            sent = await bot.send_photo(
                chat_id=LYRICS_CACHE_CHANNEL_ID,
                photo=photo_payload,
                caption=caption,
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("LYRICS_ARCHIVE_PHOTO_FAILED artist=%s title=%s", artist, title, exc_info=True)

    if sent is None:
        try:
            sent = await bot.send_message(
                chat_id=LYRICS_CACHE_CHANNEL_ID,
                text=caption,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.warning("LYRICS_ARCHIVE_SEND_FAILED artist=%s title=%s", artist, title, exc_info=True)
            return None

    try:
        await lyrics_snippet_cache_service.mark_archived(
            artist=artist,
            title=title,
            channel_chat_id=int(sent.chat.id),
            channel_message_id=int(sent.message_id),
        )
    except Exception:
        logger.warning("LYRICS_ARCHIVE_MARK_FAILED artist=%s title=%s", artist, title, exc_info=True)

    logger.info(
        "LYRICS_ARCHIVED artist=%s title=%s chat_id=%s message_id=%s",
        artist,
        title,
        getattr(sent.chat, "id", None),
        getattr(sent, "message_id", None),
    )
    return int(sent.chat.id), int(sent.message_id)
