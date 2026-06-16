"""/tly — capa imediata + letra editada na mesma publicação.

Fluxo:
1. Publica rapidamente a música com capa/foto e a legenda musical normal.
2. Busca a letra em segundo plano.
3. Se encontrar trecho, edita a legenda da mesma publicação com citação aberta.
4. Não usa Canvas; Canvas fica exclusivo do /tcanvas.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.telegram import _react_to_own_card, build_tly_payload
from app.services.connection_check import connect_hint_for, is_user_connected
from app.services.cover_cache import cover_cache_service
from app.services.lyrics import lyrics_service
from app.services.lyrics_archive import archive_tly_snippet
from app.services.music import music_service
from app.services.reactions import reactions_service

logger = logging.getLogger(__name__)
router = Router()

_TLY_COOLDOWN_SECONDS = 5.0
_TLY_USER_BOUND = 5000
_tly_last_use: dict[int, float] = {}


def _check_cooldown(user_id: int) -> float | None:
    now = time.monotonic()
    last = _tly_last_use.get(user_id, 0.0)
    elapsed = now - last
    if elapsed < _TLY_COOLDOWN_SECONDS:
        return _TLY_COOLDOWN_SECONDS - elapsed
    if len(_tly_last_use) >= _TLY_USER_BOUND:
        _tly_last_use.clear()
    _tly_last_use[user_id] = now
    return None


def _is_not_modified(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


def _caption_with_open_quote(base_caption: str, lyric_snippet: str | None, *, limit: int = 1024) -> str | None:
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


async def _register_tly_card(sent: Message, *, user_id: int, track: dict, track_id: str, card_emoji: str | None) -> None:
    try:
        await reactions_service.register_card(
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            track_id=track_id,
            owner_user_id=user_id,
            track_name=str(track.get("track_name") or "").strip() or None,
            artist_name=str(track.get("artist") or "").strip() or None,
        )
    except Exception:
        logger.exception("TLY_REGISTER_CARD_FAILED chat=%s message=%s", sent.chat.id, sent.message_id)

    try:
        await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, card_emoji)
    except Exception:
        logger.debug("TLY_REACT_FAILED chat=%s message=%s", sent.chat.id, sent.message_id, exc_info=True)


async def _send_initial_tly(message: Message, *, track_id: str, caption: str, cover: str | None) -> Message:
    if cover:
        photo = await cover_cache_service.resolve_photo(
            message.bot,
            track_id=track_id,
            cover_url=cover,
            filename="tly-cover.jpg",
        )
        try:
            return await message.answer_photo(photo=photo or cover, caption=caption, parse_mode="HTML")
        except Exception:
            logger.warning("TLY_COVER_SEND_FAILED fallback=original_or_text track_id=%s", track_id, exc_info=True)
            if photo and photo != cover:
                await cover_cache_service.forget(track_id=track_id, cover_url=cover, photo=cover)
                try:
                    return await message.answer_photo(photo=cover, caption=caption, parse_mode="HTML")
                except Exception:
                    logger.warning("TLY_ORIGINAL_COVER_SEND_FAILED fallback=text track_id=%s", track_id, exc_info=True)
    return await message.answer(caption, parse_mode="HTML")


async def _edit_tly_caption_when_lyrics_ready(
    sent: Message,
    *,
    base_caption: str,
    artist: str,
    title: str,
    cover: str | bytes | None = None,
) -> None:
    if not artist or not title:
        return

    try:
        lyric_snippet = await lyrics_service.get_snippet(artist, title)
    except Exception as exc:
        logger.warning("TLY_LYRICS_SKIPPED artist=%s track=%s error=%s", artist, title, type(exc).__name__)
        return

    new_caption = _caption_with_open_quote(base_caption, lyric_snippet)
    if not new_caption:
        return

    try:
        if getattr(sent, "photo", None):
            await sent.edit_caption(caption=new_caption, parse_mode="HTML")
        else:
            await sent.edit_text(new_caption, parse_mode="HTML")
        try:
            await archive_tly_snippet(
                sent.bot,
                artist=artist,
                title=title,
                base_caption=base_caption,
                lyric_snippet=lyric_snippet,
                cover=cover,
            )
        except Exception:
            logger.debug("TLY_ARCHIVE_SKIPPED artist=%s track=%s", artist, title, exc_info=True)
    except TelegramBadRequest as exc:
        if _is_not_modified(exc):
            return
        logger.warning("TLY_EDIT_CAPTION_FAILED chat=%s message=%s error=%s", sent.chat.id, sent.message_id, exc)
    except Exception:
        logger.exception("TLY_EDIT_CAPTION_FAILED chat=%s message=%s", sent.chat.id, sent.message_id)


@router.message(Command("tly"))
async def tly(message: Message) -> None:
    if not message.from_user:
        return

    from app.security.rate_limit import enforce_message_rate_limit

    if not await enforce_message_rate_limit(message, "tly"):
        return
    if not is_user_connected(message.from_user.id):
        await message.answer(
            connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True
        )
        return

    remaining = _check_cooldown(message.from_user.id)
    if remaining is not None:
        await message.answer(f"Aguarda {remaining:.0f}s antes de pedir outro.")
        return

    track = await music_service.get_current_or_last_played(message.from_user.id)
    if not track:
        await message.answer(
            "Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo."
        )
        return

    artist_raw = str(track.get("artist") or "").strip()
    track_name_raw = str(track.get("track_name") or "").strip()

    payload = await build_tly_payload(message, track, None)
    if not payload:
        await message.answer("Erro ao identificar a música.")
        return

    track_id, caption, cover, card_emoji = payload
    sent = await _send_initial_tly(message, track_id=track_id, caption=caption, cover=cover)
    await _register_tly_card(
        sent,
        user_id=message.from_user.id,
        track=track,
        track_id=track_id,
        card_emoji=card_emoji,
    )

    asyncio.create_task(
        _edit_tly_caption_when_lyrics_ready(
            sent,
            base_caption=caption,
            artist=artist_raw,
            title=track_name_raw,
            cover=cover,
        )
    )
