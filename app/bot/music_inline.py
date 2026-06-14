"""Inline musical seguro para TR4.

Entrada inline sem alterar os comandos normais. O resultado escolhido começa
como mensagem textual temporária e, quando o Telegram envia
``chosen_inline_result``, a própria mensagem inline é atualizada para o payload
musical final. A legenda final inline é sempre sanitizada para não conter links.

Regras desta fase:
- playing inline: capa/foto + legenda sem links.
- tly inline: somente foto de capa, nunca Canvas/vídeo.
- weekfm/monthfm inline: extratos individuais do usuário que chamou o inline.
- tnow/mosaico inline: apenas dono do código, sem tentar descobrir grupo destino.
- resultado final com foto usa file_id cacheado no Telegram; não usa photo_url.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import uuid
from dataclasses import dataclass

from aiogram import Bot, Router
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputTextMessageContent,
)

from app.bot.monthfm import _format_caption as _monthfm_caption
from app.bot.telegram import (
    _bold_unicode,
    _pick_card_emoji,
    _resolve_play_button_count,
    _track_label,
    build_playing_payload_for_user,
)
from app.bot.tnow import _gather_entries
from app.bot.weekfm import _caption as _weekfm_caption
from app.config import settings
from app.config.settings import CANVAS_CACHE_CHANNEL_ID
from app.services.connection_check import connect_hint_for, is_user_connected
from app.services.lastfm_capsule import lastfm_capsule_service
from app.services.lastfm_weekly import lastfm_weekly_service
from app.services.likes import likes_service
from app.services.lyrics import lyrics_service
from app.services.monthfm_card import render_monthfm_card
from app.services.music import music_service
from app.services.spotify import spotify_service
from app.services.tnow_card import render_tnow_card

logger = logging.getLogger(__name__)
router = Router(name="music_inline")

_INLINE_TTL_SECONDS = 300
_PENDING_MAX = 200

_ALIAS_TO_KIND: dict[str, str] = {
    "playing": "playing",
    "play": "playing",
    "tocando": "playing",
    "tly": "tly",
    "letra": "tly",
    "lyrics": "tly",
    "week": "week",
    "weekfm": "week",
    "weekly": "week",
    "semana": "week",
    "semanal": "week",
    "month": "month",
    "monthfm": "month",
    "monthly": "month",
    "mes": "month",
    "mês": "month",
    "mensal": "month",
    "tnow": "mosaic",
    "mosaic": "mosaic",
    "mosaico": "mosaic",
}

_KIND_TITLE = {
    "playing": "♫ Música atual",
    "tly": "✎ Trecho da letra",
    "week": "▦ Extrato semanal",
    "month": "◫ Extrato mensal",
    "mosaic": "✦ Mosaico musical",
}

_KIND_LOADING = {
    "playing": "Gerando música atual...",
    "tly": "Gerando trecho da letra...",
    "week": "Gerando extrato da semana do Last.fm...",
    "month": "Gerando extrato mensal do Last.fm...",
    "mosaic": "Gerando mosaico musical...",
}

_INLINE_MENU_KINDS: tuple[str, ...] = ("playing", "tly", "week", "month", "mosaic")

_LINK_TAG_RE = re.compile(r"<a\s+[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_HREF_ATTR_RE = re.compile(r"\s+href\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)
_URL_RE = re.compile(r"(?i)\b(?:https?://|tg://|t\.me/)\S+")


@dataclass(slots=True)
class _PendingInline:
    kind: str
    user_id: int
    display_name: str
    username: str | None
    arg: str | None
    created_at: float


@dataclass(slots=True)
class _InlineRender:
    caption: str
    photo: bytes | str | None = None
    filename: str = "inline.jpg"
    fallback_text: str | None = None
    deferred_artist: str | None = None
    deferred_title: str | None = None


_PENDING: dict[str, _PendingInline] = {}


def _purge_pending() -> None:
    now = time.monotonic()
    expired = [key for key, item in _PENDING.items() if now - item.created_at > _INLINE_TTL_SECONDS]
    for key in expired:
        _PENDING.pop(key, None)
    if len(_PENDING) > _PENDING_MAX:
        for key in list(_PENDING)[: len(_PENDING) - _PENDING_MAX]:
            _PENDING.pop(key, None)


def _split_query(raw: str | None) -> tuple[str | None, str | None]:
    parts = (raw or "").strip().split(maxsplit=1)
    if not parts:
        return None, None
    kind = _ALIAS_TO_KIND.get(parts[0].casefold())
    arg = parts[1].strip() if len(parts) > 1 else None
    return kind, arg or None


def is_music_inline_query(raw: str | None) -> bool:
    if not (raw or "").strip():
        return True
    kind, _arg = _split_query(raw)
    return kind is not None


def _strip_links(value: str | None) -> str:
    """Remove links da legenda mantendo HTML simples permitido."""
    text = str(value or "")
    while True:
        new_text = _LINK_TAG_RE.sub(r"\1", text)
        if new_text == text:
            break
        text = new_text
    text = _HREF_ATTR_RE.sub("", text)
    text = _URL_RE.sub("", text)
    return text.strip()


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


async def _edit_inline_caption_when_lyrics_ready(
    bot: Bot,
    inline_message_id: str,
    *,
    base_caption: str,
    artist: str,
    title: str,
    as_media: bool = True,
) -> None:
    if not artist or not title:
        return
    try:
        lyric_snippet = await lyrics_service.get_snippet(artist, title)
    except Exception as exc:
        logger.warning("MUSIC_INLINE_TLY_LYRICS_SKIPPED artist=%s track=%s error=%s", artist, title, type(exc).__name__)
        return
    new_caption = _caption_with_open_quote(base_caption, lyric_snippet)
    if not new_caption:
        return
    try:
        if as_media:
            await bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=new_caption,
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=new_caption,
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.warning("MUSIC_INLINE_TLY_EDIT_CAPTION_FAILED artist=%s track=%s error=%s", artist, title, exc)


def _is_owner(user_id: int) -> bool:
    return bool(settings.is_code_owner(user_id))


def _result_description(kind: str, allowed: bool) -> str:
    if not allowed:
        return "Acesso restrito ao dono do código."
    if kind == "tly":
        return "Usa capa estática e legenda sem links."
    if kind == "mosaic":
        return "Owner-only, sem detectar o grupo destino."
    return "Resultado final com legenda sem links."


def _build_loading_markup(result_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Atualizar",
                    callback_data=f"mi:render:{result_id}",
                )
            ]
        ]
    )


async def _clear_inline_markup(bot: Bot, inline_message_id: str) -> None:
    try:
        await bot.edit_message_reply_markup(inline_message_id=inline_message_id, reply_markup=None)
    except Exception:
        logger.debug("MUSIC_INLINE_CLEAR_MARKUP_FAILED inline_message_id=%s", inline_message_id, exc_info=True)


async def _edit_inline_rendered(bot: Bot, inline_message_id: str, rendered: _InlineRender) -> None:
    caption = _strip_links(rendered.caption)
    if rendered.photo:
        file_id = await _cache_photo_file_id(bot, rendered.photo, filename=rendered.filename)
        if file_id:
            try:
                await bot.edit_message_media(
                    inline_message_id=inline_message_id,
                    media=InputMediaPhoto(media=file_id, caption=caption[:1024], parse_mode="HTML"),
                    reply_markup=None,
                )
                await _clear_inline_markup(bot, inline_message_id)
                if rendered.deferred_artist and rendered.deferred_title:
                    asyncio.create_task(
                        _edit_inline_caption_when_lyrics_ready(
                            bot,
                            inline_message_id,
                            base_caption=caption,
                            artist=rendered.deferred_artist,
                            title=rendered.deferred_title,
                            as_media=True,
                        )
                    )
                return
            except Exception as exc:
                if "message is not modified" in str(exc).casefold():
                    logger.info("MUSIC_INLINE_EDIT_MEDIA_NOT_MODIFIED inline_message_id=%s", inline_message_id)
                    await _clear_inline_markup(bot, inline_message_id)
                    return
                logger.warning("MUSIC_INLINE_EDIT_MEDIA_FAILED_FALLBACK_TEXT inline_message_id=%s", inline_message_id, exc_info=True)
    text = _strip_links(rendered.fallback_text or caption or "Resultado indisponível.")[:3900]
    try:
        await bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=None,
        )
        await _clear_inline_markup(bot, inline_message_id)
        if rendered.deferred_artist and rendered.deferred_title:
            asyncio.create_task(
                _edit_inline_caption_when_lyrics_ready(
                    bot,
                    inline_message_id,
                    base_caption=caption,
                    artist=rendered.deferred_artist,
                    title=rendered.deferred_title,
                    as_media=False,
                )
            )
    except Exception as exc:
        if "message is not modified" in str(exc).casefold():
            logger.info("MUSIC_INLINE_EDIT_TEXT_NOT_MODIFIED inline_message_id=%s", inline_message_id)
            await _clear_inline_markup(bot, inline_message_id)
            if rendered.deferred_artist and rendered.deferred_title:
                asyncio.create_task(
                    _edit_inline_caption_when_lyrics_ready(
                        bot,
                        inline_message_id,
                        base_caption=caption,
                        artist=rendered.deferred_artist,
                        title=rendered.deferred_title,
                        as_media=False,
                    )
                )
            return
        raise


async def _cache_photo_file_id(bot: Bot, photo: bytes | str | None, *, filename: str) -> str | None:
    """Envia imagem ao canal técnico e devolve file_id reutilizável."""
    if not photo or not CANVAS_CACHE_CHANNEL_ID:
        return None
    try:
        if isinstance(photo, bytes):
            sent = await bot.send_photo(
                chat_id=CANVAS_CACHE_CHANNEL_ID,
                photo=BufferedInputFile(photo, filename=filename),
            )
        else:
            sent = await bot.send_photo(chat_id=CANVAS_CACHE_CHANNEL_ID, photo=str(photo))
        if sent.photo:
            return sent.photo[-1].file_id
    except Exception:
        logger.warning("MUSIC_INLINE_CACHE_PHOTO_FAILED filename=%s", filename, exc_info=True)
    return None


async def _render_playing(item: _PendingInline) -> _InlineRender:
    if not is_user_connected(item.user_id):
        text = _strip_links(connect_hint_for("private"))
        return _InlineRender(caption=text, fallback_text=text)
    track = await music_service.get_current_or_last_played(item.user_id)
    if not track:
        text = "Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo."
        return _InlineRender(caption=text, fallback_text=text)
    payload = await build_playing_payload_for_user(item.user_id, item.display_name, track)
    if not payload:
        return _InlineRender(caption="Erro ao identificar a música.", fallback_text="Erro ao identificar a música.")
    _track_id, caption, cover, _keyboard, _card_emoji = payload
    safe_caption = _strip_links(caption)
    return _InlineRender(caption=safe_caption, photo=cover, filename="playing-inline.jpg", fallback_text=safe_caption)


_SANS_BOLD_ITALIC_UPPER_OFFSET = 0x1D63C - ord("A")
_SANS_BOLD_ITALIC_LOWER_OFFSET = 0x1D656 - ord("a")


def _inline_name_style(value: str | None) -> str:
    raw = (value or "Usuário").strip() or "Usuário"
    out: list[str] = []
    for ch in raw:
        if "A" <= ch <= "Z":
            out.append(chr(ord(ch) + _SANS_BOLD_ITALIC_UPPER_OFFSET))
        elif "a" <= ch <= "z":
            out.append(chr(ord(ch) + _SANS_BOLD_ITALIC_LOWER_OFFSET))
        else:
            out.append(ch)
    return html.escape("".join(out))


def _inline_tly_search_query(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    for sep in (" — ", " – ", " - "):
        if sep in value:
            title, artist = value.split(sep, 1)
            title = title.strip()
            artist = artist.strip()
            if title and artist:
                return f'track:"{title}" artist:"{artist}"'
    return value


async def _search_spotify_inline_track(raw_query: str | None) -> dict | None:
    query = _inline_tly_search_query(raw_query)
    if not query:
        return None
    try:
        token = await spotify_service._get_client_credentials_token()
        if not token:
            return None
        client = spotify_service._client()
        response = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": query, "type": "track", "limit": 1, "market": "BR"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            logger.warning("MUSIC_INLINE_TLY_SEARCH_NON_200 status=%s query=%s", response.status_code, query)
            return None
        items = ((response.json().get("tracks") or {}).get("items") or [])
        if not items:
            return None
        return spotify_service._map_track(items[0], source="spotify_inline_search", played_at=None)
    except Exception:
        logger.warning("MUSIC_INLINE_TLY_SEARCH_FAILED query=%s", query, exc_info=True)
        return None


async def _resolve_inline_tly_track(item: _PendingInline) -> dict | None:
    if item.arg:
        return await _search_spotify_inline_track(item.arg)
    return await music_service.get_current_or_last_played(item.user_id)



async def _render_tly(item: _PendingInline) -> _InlineRender:
    if not item.arg and not is_user_connected(item.user_id):
        text = _strip_links(connect_hint_for("private"))
        return _InlineRender(caption=text, fallback_text=text)
    track = await _resolve_inline_tly_track(item)
    if not track:
        text = "Não encontrei essa música." if item.arg else "Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo."
        return _InlineRender(caption=text, fallback_text=text)

    artist_raw = str(track.get("artist") or "").strip()
    track_name_raw = str(track.get("track_name") or "").strip()
    lyric_snippet: str | None = None

    track_id = str(track.get("track_id") or "").strip()
    if not track_id:
        return _InlineRender(caption="Erro ao identificar a música.", fallback_text="Erro ao identificar a música.")
    try:
        await likes_service.register_play(item.user_id, track_id, track_name=track_name_raw, artist_name=artist_raw)
    except Exception:
        logger.exception("MUSIC_INLINE_TLY_REGISTER_PLAY_FAILED user=%s track=%s", item.user_id, track_id)

    total_plays, plays_source = await _resolve_play_button_count(item.user_id, track_id, artist_raw, track_name_raw)
    _ = _pick_card_emoji(total_plays, plays_source)
    track_name, artist, _track_url, cover = _track_label(track)
    name_part = _inline_name_style(item.display_name or "Usuário")
    header = f"{name_part} · ♫ {track_name} — {artist}"
    caption = header
    safe_caption = _strip_links(caption)
    return _InlineRender(
        caption=safe_caption,
        photo=cover,
        filename="tly-inline.jpg",
        fallback_text=safe_caption,
        deferred_artist=artist_raw,
        deferred_title=track_name_raw,
    )


async def _render_week(item: _PendingInline) -> _InlineRender:
    if not is_user_connected(item.user_id):
        text = _strip_links(connect_hint_for("private"))
        return _InlineRender(caption=text, fallback_text=text)
    result = await lastfm_weekly_service.build_capsule(
        user_id=item.user_id,
        display_name=item.display_name,
        raw_week=item.arg,
    )
    card_bytes = await render_monthfm_card(result.card_data) if result.card_data else None
    if card_bytes:
        caption = _strip_links(_weekfm_caption(result.card_data, item.display_name, item.user_id))
        return _InlineRender(caption=caption, photo=card_bytes, filename="weekfm-inline.jpg", fallback_text=caption)
    if result.photo_bytes:
        caption = _strip_links(_weekfm_caption(result.card_data, item.display_name, item.user_id))
        return _InlineRender(caption=caption, photo=result.photo_bytes, filename="weekfm-inline.jpg", fallback_text=caption)
    text = _strip_links(result.text)
    return _InlineRender(caption=text[:3900], fallback_text=text[:3900])


async def _render_month(item: _PendingInline) -> _InlineRender:
    if not is_user_connected(item.user_id):
        text = _strip_links(connect_hint_for("private"))
        return _InlineRender(caption=text, fallback_text=text)
    result = await lastfm_capsule_service.build_capsule(
        user_id=item.user_id,
        display_name=item.display_name,
        raw_month=item.arg,
    )
    card_bytes = await render_monthfm_card(result.card_data) if result.card_data else None
    if card_bytes:
        caption = _strip_links(_monthfm_caption(result.card_data, item.arg, item.display_name, item.user_id))
        return _InlineRender(caption=caption, photo=card_bytes, filename="monthfm-inline.jpg", fallback_text=caption)
    if result.photo_bytes:
        caption = _strip_links(result.text if len(result.text) <= 1024 else "♫ Extrato mensal")
        return _InlineRender(caption=caption, photo=result.photo_bytes, filename="monthfm-inline.jpg", fallback_text=caption)
    text = _strip_links(result.text)
    return _InlineRender(caption=text[:3900], fallback_text=text[:3900])


async def _render_mosaic(bot: Bot, item: _PendingInline) -> _InlineRender:
    if not _is_owner(item.user_id):
        text = "Acesso restrito ao dono do código."
        return _InlineRender(caption=text, fallback_text=text)
    entries = await _gather_entries(bot, chat=None)
    if not entries:
        text = "Ninguém cadastrado está com música tocando agora."
        return _InlineRender(caption=text, fallback_text=text)
    card_bytes = await render_tnow_card(entries)
    caption = f"♫ <b>tocando agora</b> • {len(entries)} pessoa{'s' if len(entries) != 1 else ''}"
    safe_caption = _strip_links(caption)
    if card_bytes:
        return _InlineRender(caption=safe_caption, photo=card_bytes, filename="tnow-inline.jpg", fallback_text=safe_caption)
    lines = [safe_caption]
    for entry in entries:
        lines.append(
            f"• <b>{html.escape(entry.display_name)}</b> — {html.escape(entry.track_name)} <i>({html.escape(entry.artist)})</i>"
        )
    text = _strip_links("\n".join(lines))[:3900]
    return _InlineRender(caption=text, fallback_text=text)


async def _render(bot: Bot, item: _PendingInline) -> _InlineRender:
    if item.kind == "playing":
        return await _render_playing(item)
    if item.kind == "tly":
        return await _render_tly(item)
    if item.kind == "week":
        return await _render_week(item)
    if item.kind == "month":
        return await _render_month(item)
    if item.kind == "mosaic":
        return await _render_mosaic(bot, item)
    return _InlineRender(caption="Comando inline indisponível.", fallback_text="Comando inline indisponível.")


@router.inline_query(lambda query: is_music_inline_query(query.query))
async def music_inline_query(query: InlineQuery) -> None:
    kind, arg = _split_query(query.query)

    def _make_result(item_kind: str, item_arg: str | None) -> InlineQueryResultArticle | None:
        allowed = item_kind != "mosaic" or _is_owner(query.from_user.id)
        if not allowed:
            return None
        result_id = f"mi:{item_kind}:{uuid.uuid4().hex[:12]}"
        _PENDING[result_id] = _PendingInline(
            kind=item_kind,
            user_id=int(query.from_user.id),
            display_name=query.from_user.full_name or "Usuário",
            username=query.from_user.username,
            arg=item_arg,
            created_at=time.monotonic(),
        )
        return InlineQueryResultArticle(
            id=result_id,
            title=_KIND_TITLE[item_kind],
            description=_result_description(item_kind, allowed),
            input_message_content=InputTextMessageContent(
                message_text=html.escape(_KIND_LOADING[item_kind]),
                parse_mode="HTML",
            ),
            reply_markup=_build_loading_markup(result_id),
        )

    _purge_pending()

    if not kind:
        results = [
            result
            for item_kind in _INLINE_MENU_KINDS
            for result in [_make_result(item_kind, None)]
            if result is not None
        ]
        await query.answer(results, cache_time=1, is_personal=True)
        return

    result = _make_result(kind, arg)
    if result is None:
        await query.answer([], cache_time=1, is_personal=True)
        return
    await query.answer([result], cache_time=1, is_personal=True)


@router.callback_query(lambda query: str(query.data or "").startswith("mi:render:"))
async def music_inline_render_callback(query: CallbackQuery, bot: Bot) -> None:
    """Botão técnico: só responde ao clique acidental.

    O botão existe para o Telegram anexar inline keyboard e assim entregar
    inline_message_id. A renderização oficial continua no chosen_inline_result.
    Se o usuário clicar sem querer, não renderiza uma segunda vez e não gera erro.
    """
    result_id = str(query.data or "").removeprefix("mi:render:")
    inline_message_id = getattr(query, "inline_message_id", None)
    try:
        await query.answer("Gerando…", show_alert=False)
    except Exception:
        logger.debug("MUSIC_INLINE_CALLBACK_ANSWER_FAILED result_id=%s", result_id, exc_info=True)
    if not inline_message_id:
        logger.info("MUSIC_INLINE_CALLBACK_WITHOUT_INLINE_MESSAGE_ID result_id=%s", result_id)
        return
    logger.info("MUSIC_INLINE_RENDER_BUTTON_TAPPED_IGNORED result_id=%s", result_id)


@router.chosen_inline_result(lambda result: str(result.result_id or "").startswith("mi:"))
async def music_inline_chosen(result: ChosenInlineResult, bot: Bot) -> None:
    inline_message_id = getattr(result, "inline_message_id", None)
    if not inline_message_id:
        logger.info("MUSIC_INLINE_CHOSEN_WITHOUT_INLINE_MESSAGE_ID result_id=%s", result.result_id)
        return
    item = _PENDING.pop(str(result.result_id), None)
    if item is None:
        parts = str(result.result_id or "").split(":", 2)
        kind = parts[1] if len(parts) >= 2 else ""
        item = _PendingInline(
            kind=kind,
            user_id=int(result.from_user.id),
            display_name=result.from_user.full_name or "Usuário",
            username=result.from_user.username,
            arg=None,
            created_at=time.monotonic(),
        )

    try:
        rendered = await _render(bot, item)
        await _edit_inline_rendered(bot, inline_message_id, rendered)
    except Exception:
        logger.exception("MUSIC_INLINE_RENDER_FAILED result_id=%s kind=%s", result.result_id, item.kind)
        try:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="Não consegui gerar esse inline agora. Tente novamente em instantes.",
            )
        except Exception:
            logger.exception("MUSIC_INLINE_FAILURE_EDIT_FAILED result_id=%s", result.result_id)
