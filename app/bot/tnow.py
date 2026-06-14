"""/tnow — mosaico ao vivo do que cada membro cadastrado está ouvindo agora.

Critérios:
- Considera todo user_id presente em `spotify_tokens` OU `lastfm_profiles`.
- Quando rodado em grupo/supergrupo, restringe ao subconjunto que é membro
  daquele chat. Em DM/privado, lista
  todos os cadastrados.
- Mantém SOMENTE quem está com música em reprodução neste exato momento
  (Spotify currently-playing == 200 AND is_playing=true, OU Last.fm
  @attr.nowplaying == true).
- Quem pausou / parou é ignorado.

Privacidade: o pré-requisito p/ aparecer é o usuário ter conectado
voluntariamente Spotify ou Last.fm ao bot, então o card só revela o que
ele já consentiu em expor por meio dos comandos individuais. Em grupo,
o filtro de membership garante que ninguém de fora apareça no mosaico.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Chat, Message
from sqlalchemy import select

from app.config.settings import HTTP_TIMEOUT_SECONDS
from app.db.database import SessionLocal
from app.models.lastfm_profile import LastfmProfile
from app.models.spotify_token import SpotifyToken
from app.services.lastfm import lastfm_service
from app.services.spotify import spotify_service
from app.services.tnow_card import TnowEntry, render_tnow_card

logger = logging.getLogger(__name__)
router = Router(name="tnow")

# Limite duro para evitar requests excessivos e cards gigantes. Acima disso
# o serviço ainda funciona mas trunca os primeiros N a responderem.
MAX_USERS = 60
MAX_TILES = 30
COVER_FETCH_TIMEOUT = 8.0

TNOW_RECENT_YELLOW_MINUTES = 15
TNOW_RECENT_RED_MINUTES = 30
_TNOW_STATUS_PRIORITY = {
    "live": 0,
    "recent_15": 1,
    "recent_30": 2,
    "stale": 3,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_played_at(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        logger.debug("TNOW_PLAYED_AT_PARSE_FAILED | value=%s", raw, exc_info=True)
        return None


def _classify_tnow_track(track: dict[str, Any] | None, *, source_tag: str, now: datetime) -> dict[str, Any] | None:
    if not track:
        return None

    source = str(track.get("source") or "")
    is_live = source in {"spotify_current", "lastfm_current"}
    if source == "spotify_current" and not bool(track.get("is_playing", True)):
        is_live = False

    out = dict(track)
    out["_source_tag"] = source_tag

    if is_live:
        out["_tnow_status"] = "live"
        out["_tnow_age_minutes"] = 0
        return out

    if source not in {"spotify_last", "lastfm_last", "spotify_current"}:
        return None

    played_at = _parse_played_at(out.get("played_at"))
    if played_at is None:
        return None

    age_seconds = max(0.0, (now - played_at).total_seconds())
    age_minutes = int(age_seconds // 60)
    out["_tnow_age_minutes"] = age_minutes
    out["_tnow_played_at_iso"] = played_at.isoformat()

    if age_seconds <= TNOW_RECENT_YELLOW_MINUTES * 60:
        out["_tnow_status"] = "recent_15"
    elif age_seconds <= TNOW_RECENT_RED_MINUTES * 60:
        out["_tnow_status"] = "recent_30"
    else:
        out["_tnow_status"] = "stale"
    return out


def _candidate_sort_key(track: dict[str, Any]) -> tuple[int, int, int]:
    status = str(track.get("_tnow_status") or "stale")
    source = str(track.get("_source_tag") or "")
    age = int(track.get("_tnow_age_minutes") or 0)
    return (
        _TNOW_STATUS_PRIORITY.get(status, 9),
        0 if source == "spotify" else 1,
        age,
    )


def _entry_sort_key(entry: TnowEntry) -> tuple[int, int, str]:
    return (
        _TNOW_STATUS_PRIORITY.get(entry.status, 9),
        0 if entry.source == "spotify" else 1,
        entry.display_name.lower(),
    )


def _grid_slots(n: int) -> int:
    if n <= 0:
        return 0
    import math

    if n <= 1:
        columns = 1
    elif n == 3:
        columns = 3
    elif n == 5:
        columns = 5
    else:
        columns = min(6, max(2, math.ceil(math.sqrt(n))))
    return columns * math.ceil(n / columns)




def _registered_user_ids() -> list[int]:
    with SessionLocal() as db:
        spotify_ids = db.execute(select(SpotifyToken.user_id)).scalars().all()
        lastfm_ids = db.execute(select(LastfmProfile.user_id)).scalars().all()
    seen: set[int] = set()
    out: list[int] = []
    for uid in (*spotify_ids, *lastfm_ids):
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out[:MAX_USERS]


async def _fetch_cover(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=COVER_FETCH_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.content
    except Exception:
        logger.debug("TNOW_COVER_FETCH_FAILED | url=%s", url, exc_info=True)
    return None


async def _resolve_now_playing(user_id: int, *, now: datetime) -> dict[str, Any] | None:
    """Resolve a faixa do mosaico.

    Prioridade:
    1. ao vivo real;
    2. última faixa até 15 min;
    3. última faixa até 30 min;
    4. antiga, apenas para preencher grade.
    """
    candidates: list[dict[str, Any]] = []

    try:
        sp = await spotify_service.get_current_or_last_played(user_id)
    except Exception:
        logger.exception("TNOW_SPOTIFY_PROBE_FAILED | user_id=%s", user_id)
        sp = None
    sp_candidate = _classify_tnow_track(sp, source_tag="spotify", now=now)
    if sp_candidate:
        if sp_candidate.get("_tnow_status") == "live":
            return sp_candidate
        candidates.append(sp_candidate)

    try:
        lf = await lastfm_service.get_current_or_last_played(user_id)
    except Exception:
        logger.exception("TNOW_LASTFM_PROBE_FAILED | user_id=%s", user_id)
        lf = None
    lf_candidate = _classify_tnow_track(lf, source_tag="lastfm", now=now)
    if lf_candidate:
        candidates.append(lf_candidate)

    if not candidates:
        return None

    candidates.sort(key=_candidate_sort_key)
    return candidates[0]




def _lastfm_display_name(user_id: int) -> str | None:
    """Fallback visual for imported users whose Telegram profile is not reachable.

    Imported music users may exist only in lastfm_profiles/spotify_tokens. When
    Telegram get_chat fails, never expose the numeric Telegram ID in the mosaic;
    prefer the Last.fm username already stored by the user, then a neutral label.
    """
    try:
        with SessionLocal() as db:
            username = db.execute(
                select(LastfmProfile.username).where(LastfmProfile.user_id == user_id)
            ).scalar_one_or_none()
    except Exception:
        logger.debug("TNOW_LASTFM_NAME_LOOKUP_FAILED | user_id=%s", user_id, exc_info=True)
        return None
    username = str(username or "").strip()
    return username or None


async def _display_name(bot: Any, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
        name = getattr(chat, "full_name", None) or getattr(chat, "first_name", None)
        if name:
            return name
        username = getattr(chat, "username", None)
        if username:
            return f"@{username}"
    except Exception:
        logger.debug("TNOW_GET_CHAT_FAILED | user_id=%s", user_id, exc_info=True)

    lastfm_username = _lastfm_display_name(user_id)
    if lastfm_username:
        return lastfm_username
    return "Usuário cadastrado"


async def _build_entry(bot: Any, user_id: int, *, now: datetime) -> TnowEntry | None:
    track = await _resolve_now_playing(user_id, now=now)
    if not track:
        return None
    cover_bytes = await _fetch_cover(track.get("album_image_url") or track.get("cover"))
    display_name = await _display_name(bot, user_id)
    return TnowEntry(
        user_id=user_id,
        display_name=display_name,
        track_name=str(track.get("track_name") or "—"),
        artist=str(track.get("artist") or "—"),
        cover_bytes=cover_bytes,
        source=str(track.get("_source_tag") or "spotify"),
        status=str(track.get("_tnow_status") or "live"),
        age_minutes=int(track.get("_tnow_age_minutes") or 0),
    )



_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_MEMBER_OUT_STATUSES = {"left", "ki" + "cked"}


async def _is_chat_member(bot: Any, chat_id: int, user_id: int) -> bool:
    """True se o usuário é membro ativo do chat. Erros (ex.: bot sem
    a plataforma não devolver dados suficientes) caem em False — preferimos esconder
    do que vazar alguém que talvez não esteja mais no grupo."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = getattr(member, "status", None)
        status_value = getattr(status, "value", status)
        return str(status_value) not in _MEMBER_OUT_STATUSES
    except Exception:
        logger.debug(
            "TNOW_GET_CHAT_MEMBER_FAILED | chat_id=%s | user_id=%s",
            chat_id, user_id, exc_info=True,
        )
        return False


async def _filter_to_group_members(bot: Any, chat_id: int, user_ids: list[int]) -> list[int]:
    if not user_ids:
        return []
    checks = await asyncio.gather(
        *[_is_chat_member(bot, chat_id, uid) for uid in user_ids],
        return_exceptions=False,
    )
    return [uid for uid, ok in zip(user_ids, checks) if ok]


async def _gather_entries(bot: Any, chat: Chat | None = None) -> list[TnowEntry]:
    registered_user_ids = _registered_user_ids()
    if not registered_user_ids:
        logger.info("TNOW_GATHER_RESULT | registered=0 | members=0 | fresh=0 | stale=0 | selected=0")
        return []

    user_ids = registered_user_ids
    if chat is not None and chat.type in _GROUP_TYPES:
        user_ids = await _filter_to_group_members(bot, chat.id, user_ids)
        if not user_ids:
            logger.info(
                "TNOW_GATHER_RESULT | registered=%s | members=0 | fresh=0 | stale=0 | selected=0 | chat_id=%s",
                len(registered_user_ids),
                chat.id,
            )
            return []

    now = _utcnow()
    tasks = [asyncio.create_task(_build_entry(bot, uid, now=now)) for uid in user_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    fresh: list[TnowEntry] = []
    stale: list[TnowEntry] = []
    raised = 0
    empty = 0

    for item in results:
        if isinstance(item, TnowEntry):
            if item.status == "stale":
                stale.append(item)
            else:
                fresh.append(item)
        elif isinstance(item, Exception):
            raised += 1
            logger.debug("TNOW_BUILD_ENTRY_RAISED", exc_info=item)
        else:
            empty += 1

    fresh.sort(key=_entry_sort_key)
    stale.sort(key=_entry_sort_key)

    selected = fresh[:MAX_TILES]
    if selected and len(selected) < MAX_TILES:
        missing = min(_grid_slots(len(selected)) - len(selected), MAX_TILES - len(selected))
        if missing > 0:
            selected.extend(stale[:missing])

    logger.info(
        "TNOW_GATHER_RESULT | registered=%s | members=%s | fresh=%s | stale=%s | selected=%s | empty=%s | raised=%s | chat_id=%s",
        len(registered_user_ids),
        len(user_ids),
        len(fresh),
        len(stale),
        len(selected),
        empty,
        raised,
        getattr(chat, "id", None),
    )

    return selected




async def _finish_tnow(status: Message) -> None:
    try:
        entries = await _gather_entries(status.bot)
        if not entries:
            await status.edit_text(
                "Ninguém cadastrado está com música tocando agora. 🦗\n"
                "Conecta seu Spotify ou Last.fm e bota algo no replay."
            )
            return

        card_bytes = await render_tnow_card(entries)
        caption = f"♫ <b>ao vivo e recentes</b> • {len(entries)} pessoa{'s' if len(entries) != 1 else ''}"
        if card_bytes:
            sent = await status.answer_photo(
                photo=BufferedInputFile(card_bytes, filename="tnow.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
            # Sprint 11: bot reage 🔥 no mosaico do grupo.
            from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_TNOW
            await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, _CARD_EMOJI_TNOW)
            return

        # Fallback textual quando Playwright não está disponível ou falhou.
        lines = [caption]
        for entry in entries:
            safe_name = html.escape(entry.display_name)
            safe_track = html.escape(entry.track_name)
            safe_artist = html.escape(entry.artist)
            lines.append(f"• <b>{safe_name}</b> — {safe_track} <i>({safe_artist})</i>")
        await status.edit_text("\n".join(lines), parse_mode="HTML")
    except Exception:
        logger.exception("TNOW_FAILED")
        try:
            await status.edit_text("Não consegui montar o mosaico agora. Tenta de novo em alguns segundos.")
        except Exception:
            logger.exception("TNOW_FAILURE_MESSAGE_FAILED")


# I4: mantém ref forte das background tasks pra GC não coletar antes do término.
_BG_TASKS: set[asyncio.Task] = set()


@router.message(Command("tnow"))
async def tnow(message: Message) -> None:
    if not message.from_user:
        return
    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "tnow"):
        return
    # Quem manda /tnow sem ter conectado nada não vai aparecer no próprio
    # mosaico — orienta antes pra evitar confusão. Não bloqueia o comando:
    # ele segue mostrando quem mais tá ouvindo.
    from app.services.connection_check import connect_hint_for, is_user_connected
    if not is_user_connected(message.from_user.id):
        await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
    # U1: chat_action enquanto resolve playing de todos + monta mosaico.
    try:
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass
    status = await message.answer("Vendo quem tá ouvindo o quê agora...")
    task = asyncio.create_task(_finish_tnow(status))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
