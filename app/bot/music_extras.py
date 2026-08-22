from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.music_groups import list_groups
from app.bot.music_command_runner import MusicCommandError, execute_nowp_publish
from app.services.likes import likes_service
from app.services.cover_cache import cover_cache_service
from app.services.music import music_service
from app.services.reactions import reactions_service  # Sprint 8

logger = logging.getLogger(__name__)


def _normalize_optional_text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if value is None:
        return None
    try:
        cleaned = str(value).strip()
    except Exception:
        return None
    return cleaned or None


def _safe_button(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    if style:
        try:
            return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)  # type: ignore[call-arg]
        except Exception:
            # Sprint 4 (S4.2): aiogram pode não suportar `style=` (depende
            # da versão / API do Telegram). Detecção em runtime + fallback
            # silencioso por design — DEBUG basta pra investigar se for
            # preciso (em prod usa fallback toda vez sem ruído no log).
            logger.debug("InlineKeyboardButton style fallback | text=%s", text, exc_info=True)
    return InlineKeyboardButton(text=text, callback_data=callback_data)


_NOWP_MEMBER_CHECK_CONCURRENCY = 10


async def _list_common_groups(bot, user_id: int) -> list[dict]:
    """Grupos conhecidos onde o usuário também participa.

    Faz `get_chat_member` por grupo em paralelo. A filtragem apenas evita
    exibir destinos onde o usuário não pode receber a publicação musical.
    """
    groups = list_groups(50)
    sem = asyncio.Semaphore(_NOWP_MEMBER_CHECK_CONCURRENCY)

    async def _check(group: dict) -> dict | None:
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            return None
        async with sem:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
            except Exception:
                return None
        status = getattr(member, "status", None)
        if status in {"left", "kicked"}:
            return None
        if status == "restricted" and not getattr(member, "is_member", True):
            return None
        return group

    checked = await asyncio.gather(*(_check(g) for g in groups))
    return [g for g in checked if g is not None]


def _nowp_groups_keyboard(requester_id: int, groups: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups[:10]:
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            continue
        # Telegram caps callback_data em 64 bytes. requester_id (Telegram ID,
        # até 19 dígitos no futuro) + chat_id de supergrupo negativo longo
        # (ex: -1001234567890123) podem estourar em edge cases. Se estourar,
        # pula o botão (mensagem do picker ainda funciona, só esse grupo fica
        # de fora). Sem fallback complexo de índice — simplicidade > 0.1% de cobertura.
        callback_data = f"nowp:send:{requester_id}:{chat_id}"
        if len(callback_data.encode("utf-8")) > 64:
            logger.warning(
                "NOWP_CALLBACK_TOO_LONG | requester=%s chat_id=%s len=%s",
                requester_id, chat_id, len(callback_data.encode("utf-8")),
            )
            continue
        title = str(group.get("title") or chat_id)
        label = title if len(title) <= 40 else title[:37] + "..."
        rows.append([_safe_button(label, callback_data, "primary")])
    rows.append([_safe_button("Fechar", f"nowp:close:{requester_id}", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_albnow(user_name: str, user_id: int, data: dict) -> str:
    safe_user = html.escape(user_name or "Usuário")
    user_link = f"tg://user?id={int(user_id)}"
    user_part = f'<b><a href="{html.escape(user_link, quote=True)}">{safe_user}</a></b>'
    album = html.escape(str(data.get("album_name") or ""))
    artist = html.escape(str(data.get("artist") or ""))
    track = html.escape(str(data.get("track_name") or ""))
    album_url = html.escape(str(data.get("album_url") or data.get("spotify_url") or ""), quote=True)

    if album_url:
        title = album or track or "Música"
        return f"{user_part} · <i>♪ <b><a href=\"{album_url}\">{title}</a></b> — {artist}</i>"
    if track and artist:
        return f"{user_part} · <i>♬ {track} — {artist}</i>"
    return f"{user_part} · <i>nada tocando agora</i>"


def register_music_extra_handlers(dp: Dispatcher) -> None:
    @dp.message(Command("albnow"))
    async def albnow(message: Message) -> None:
        if not message.from_user:
            return
        from app.security.rate_limit import enforce_message_rate_limit
        if not await enforce_message_rate_limit(message, "albnow"):
            return
        from app.services.connection_check import connect_hint_for, is_user_connected
        if not is_user_connected(message.from_user.id):
            await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
            return
        # Sprint 3.5: usa music_service (Last.fm-first) pra manter o
        # comportamento do antigo music_proxy.
        data = await music_service.get_current_or_last_played(message.from_user.id)
        if not data:
            await message.answer("Nada tocando agora.")
            return
        caption = _format_albnow(message.from_user.full_name, message.from_user.id, data)
        cover = data.get("album_image_url") or data.get("cover_url")
        if cover:
            photo = await cover_cache_service.resolve_photo(
                message.bot,
                track_id=str(data.get("track_id") or "").strip() or None,
                cover_url=str(cover),
                filename="albnow-cover.jpg",
            )
            try:
                sent = await message.answer_photo(photo=photo or str(cover), caption=caption, parse_mode="HTML")
            except Exception:
                logger.warning("ALBNOW_COVER_SEND_FAILED fallback=original_or_text", exc_info=True)
                if photo and photo != str(cover):
                    await cover_cache_service.forget(
                        track_id=str(data.get("track_id") or "").strip() or None,
                        cover_url=str(cover),
                        photo=str(cover),
                    )
                    try:
                        sent = await message.answer_photo(photo=str(cover), caption=caption, parse_mode="HTML")
                    except Exception:
                        sent = await message.answer(caption, parse_mode="HTML")
                else:
                    sent = await message.answer(caption, parse_mode="HTML")
        else:
            sent = await message.answer(caption, parse_mode="HTML")
        # Sprint 10: bot reage 🔥 no card de álbum. /albnow não calcula
        # playcount Last.fm (foco no álbum, não na faixa), então usa
        # sempre o emoji default — sem threshold ❤.
        from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_DEFAULT
        await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, _CARD_EMOJI_DEFAULT)

    @dp.message(Command("nowp"))
    async def nowp(message: Message) -> None:
        # Público: qualquer user pode rodar. Mostra picker dos grupos em comum
        # (bot + user). Envio efetivo via callback nowp:send:<uid>:<chat_id>.
        if not message.from_user or not message.bot:
            return
        from app.security.rate_limit import enforce_message_rate_limit
        if not await enforce_message_rate_limit(message, "nowp"):
            return
        from app.services.connection_check import connect_hint_for, is_user_connected
        if not is_user_connected(message.from_user.id):
            await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
            return
        status_msg = await message.answer("Procurando grupos em comum...")
        common = await _list_common_groups(message.bot, message.from_user.id)
        if not common:
            await status_msg.edit_text(
                "Nenhum grupo em comum encontrado.\n"
                "(O bot precisa estar nos mesmos grupos que você e ter recebido pelo menos uma mensagem lá.)"
            )
            return
        await status_msg.edit_text(
            "♫ Pra qual grupo enviar sua música atual?",
            reply_markup=_nowp_groups_keyboard(message.from_user.id, common),
        )

    @dp.callback_query(F.data.startswith("nowp:send:"))
    async def nowp_send_callback(query: CallbackQuery) -> None:
        if not query.from_user or not query.data or not query.message or not query.bot:
            await query.answer()
            return
        parts = query.data.split(":")
        if len(parts) != 4:
            await query.answer()
            return
        try:
            requester_id = int(parts[2])
            target_chat_id = int(parts[3])
        except ValueError:
            await query.answer()
            return
        if query.from_user.id != requester_id:
            await query.answer("Esse menu não é seu.", show_alert=True)
            return
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.answer("Enviando...")
        try:
            result = await execute_nowp_publish(
                query.bot,
                requester_id=requester_id,
                requester_name=query.from_user.full_name or "Usuário",
                group_ref=target_chat_id,
            )
        except MusicCommandError as exc:
            try:
                await query.message.edit_text(html.escape(exc.message), parse_mode="HTML")
            except Exception:
                logger.warning(
                    "NOWP_EDIT_FAILED | branch=%s | requester=%s | target=%s",
                    exc.code,
                    requester_id,
                    target_chat_id,
                    exc_info=True,
                )
            return
        try:
            await query.message.edit_text(html.escape(result.message), parse_mode="HTML")
        except Exception:
            logger.warning(
                "NOWP_EDIT_FAILED | branch=success | requester=%s | target=%s",
                requester_id,
                target_chat_id,
                exc_info=True,
            )

    @dp.callback_query(F.data.startswith("nowp:close:"))
    async def nowp_close_callback(query: CallbackQuery) -> None:
        if not query.from_user or not query.data:
            await query.answer()
            return
        parts = query.data.split(":")
        if len(parts) != 3:
            await query.answer()
            return
        try:
            requester_id = int(parts[2])
        except ValueError:
            await query.answer()
            return
        if query.from_user.id != requester_id:
            await query.answer("Esse menu não é seu.", show_alert=True)
            return
        if query.message:
            try:
                await query.message.edit_text("/nowp fechado.")
            except Exception:
                pass
        await query.answer()
