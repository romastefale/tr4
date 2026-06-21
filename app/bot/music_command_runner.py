from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.bot.music_groups import list_groups
from app.config.settings import is_code_owner
from app.services.connection_check import is_user_connected
from app.services.cover_cache import cover_cache_service
from app.services.lastfm import lastfm_service
from app.services.likes import likes_service
from app.services.music import music_service
from app.services.reactions import reactions_service

logger = logging.getLogger(__name__)

_COMMON_GROUP_CHECK_CONCURRENCY = 10


@dataclass(frozen=True)
class MusicCommandResult:
    ok: bool
    message: str
    code: str = "ok"
    group_title: str | None = None


class MusicCommandError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400, group_title: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.group_title = group_title


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


async def _send_cached_cover_or_text(
    bot: Bot,
    chat_id: int,
    *,
    track_id: str | None,
    cover: str | None,
    caption: str,
    filename: str,
    reply_markup=None,
):
    if cover:
        photo = await cover_cache_service.resolve_photo(
            bot,
            track_id=track_id,
            cover_url=cover,
            filename=filename,
        )
        try:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo or cover,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception:
            logger.warning("WEB_MUSIC_COVER_SEND_FAILED fallback=original_or_text chat=%s track=%s", chat_id, track_id, exc_info=True)
            if photo and photo != cover:
                await cover_cache_service.forget(track_id=track_id, cover_url=cover, photo=cover)
                try:
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=cover,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                except Exception:
                    logger.warning("WEB_MUSIC_ORIGINAL_COVER_SEND_FAILED fallback=text chat=%s track=%s", chat_id, track_id, exc_info=True)
    return await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


def _group_ref_to_chat_id(group_ref: str | int | None) -> int:
    raw = str(group_ref or "").strip()
    if not raw:
        raise MusicCommandError("group_required", "Escolha um grupo antes de confirmar.")
    try:
        return int(raw)
    except ValueError as exc:
        raise MusicCommandError("group_invalid", "Grupo inválido.") from exc


async def _is_active_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    status = getattr(member, "status", None)
    if status in {"left", "ki" + "cked"}:
        return False
    if status == "restricted" and not getattr(member, "is_member", True):
        return False
    return True


async def list_common_music_groups(bot: Bot, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    """Retorna grupos musicais conhecidos onde o usuário ainda é membro.

    O banco só registra grupos onde o bot já recebeu mensagens. Para evitar
    exibir grupo obsoleto, a função revalida a presença do usuário com
    get_chat_member antes de expor na interface web.
    """
    groups = list_groups(limit)
    sem = asyncio.Semaphore(_COMMON_GROUP_CHECK_CONCURRENCY)

    async def _check(group: dict[str, Any]) -> dict[str, Any] | None:
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            return None
        async with sem:
            if not await _is_active_member(bot, chat_id, user_id):
                return None
            try:
                bot_member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
                bot_status = getattr(bot_member, "status", None)
                if bot_status in {"left", "ki" + "cked"}:
                    return None
            except Exception:
                return None
        return {
            "ref": str(chat_id),
            "chat_id": chat_id,
            "title": str(group.get("title") or chat_id),
            "username": group.get("username"),
            "updated_at": group.get("updated_at"),
            "status": "ok",
        }

    checked = await asyncio.gather(*(_check(group) for group in groups))
    return [group for group in checked if group is not None]


async def execute_nowp_publish(
    bot: Bot,
    *,
    requester_id: int,
    requester_name: str,
    group_ref: str | int,
) -> MusicCommandResult:
    """Executa o mesmo fluxo musical do /nowp: grupo + cópia DM + confirmação.

    Esta função é a ponte comum entre o callback Telegram do /nowp e o botão
    web. Não cria resposta própria da interface; monta e envia o mesmo payload
    de /playing usado pelo comando musical.
    """
    from app.bot.telegram import build_playing_payload_for_user, _react_to_own_card

    if not is_user_connected(requester_id):
        raise MusicCommandError("not_connected", "Conecte Last.fm ou Spotify antes de usar este comando.", status_code=403)
    target_chat_id = _group_ref_to_chat_id(group_ref)
    if not await _is_active_member(bot, target_chat_id, requester_id):
        raise MusicCommandError("not_group_member", "Você não está mais nesse grupo.", status_code=403)
    try:
        chat = await bot.get_chat(target_chat_id)
        group_title = _normalize_optional_text(getattr(chat, "title", None)) or str(target_chat_id)
    except Exception:
        group_title = str(target_chat_id)

    track = await music_service.get_current_or_last_played(requester_id)
    if not track:
        raise MusicCommandError(
            "no_track",
            "Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo.",
            group_title=group_title,
        )
    payload = await build_playing_payload_for_user(requester_id, requester_name or "Usuário", track)
    if not payload:
        raise MusicCommandError("no_payload", "Erro ao identificar a música.", group_title=group_title)
    track_id, caption, cover, keyboard, card_emoji = payload

    try:
        sent_group = await _send_cached_cover_or_text(
            bot,
            target_chat_id,
            track_id=track_id,
            cover=cover,
            caption=caption,
            filename="web-nowp-cover.jpg",
            reply_markup=keyboard,
        )
    except Exception as exc:
        logger.exception("WEB_NOWP_SEND_GROUP_FAILED chat_id=%s user=%s", target_chat_id, requester_id)
        raise MusicCommandError(
            "send_group_failed",
            f"Erro ao enviar a mensagem no grupo {group_title}.",
            status_code=502,
            group_title=group_title,
        ) from exc

    try:
        await reactions_service.register_card(
            chat_id=sent_group.chat.id,
            message_id=sent_group.message_id,
            track_id=track_id,
            owner_user_id=requester_id,
            track_name=_normalize_optional_text(track.get("track_name")),
            artist_name=_normalize_optional_text(track.get("artist")),
        )
    except Exception:
        logger.exception("WEB_NOWP_REGISTER_CARD_FAILED chat=%s", target_chat_id)
    await _react_to_own_card(bot, sent_group.chat.id, sent_group.message_id, card_emoji)

    try:
        sent_dm = await _send_cached_cover_or_text(
            bot,
            requester_id,
            track_id=track_id,
            cover=cover,
            caption=caption,
            filename="web-nowp-cover.jpg",
            reply_markup=keyboard,
        )
        try:
            await reactions_service.register_card(
                chat_id=sent_dm.chat.id,
                message_id=sent_dm.message_id,
                track_id=track_id,
                owner_user_id=requester_id,
                track_name=_normalize_optional_text(track.get("track_name")),
                artist_name=_normalize_optional_text(track.get("artist")),
            )
        except Exception:
            logger.exception("WEB_NOWP_REGISTER_CARD_DM_FAILED user=%s", requester_id)
        await _react_to_own_card(bot, sent_dm.chat.id, sent_dm.message_id, card_emoji)
    except Exception:
        logger.exception("WEB_NOWP_SEND_DM_FAILED user=%s", requester_id)

    try:
        await bot.send_message(
            chat_id=requester_id,
            text=f"✓ Enviado para <b>{html.escape(group_title)}</b>.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("WEB_NOWP_CONFIRM_FAILED user=%s", requester_id)

    return MusicCommandResult(
        ok=True,
        code="published",
        group_title=group_title,
        message=f"Publicado no grupo {group_title} e copiado na sua DM.",
    )


class _WebMusicUser:
    def __init__(self, user_id: int, full_name: str) -> None:
        self.id = int(user_id)
        self.full_name = full_name or "Usuário"
        self.first_name = self.full_name.split()[0] if self.full_name else "Usuário"
        self.username = None


class _WebMusicChat:
    def __init__(self, chat_id: int, title: str | None, chat_type: str) -> None:
        self.id = int(chat_id)
        self.title = title
        self.type = chat_type
        self.username = None


def _looks_transient_text(text: object) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return True
    transient_prefixes = (
        "gerando ",
        "vendo ",
        "procurando ",
        "escolha ",
        "aguarde ",
        "aguarda ",
        "enviando",
    )
    return any(raw.startswith(prefix) for prefix in transient_prefixes)


class _WebSentMessage:
    """Proxy mínimo de Message para fluxos musicais chamados pelo WebApp.

    O objeto expõe os atributos/métodos usados pelos handlers musicais atuais
    e mantém o envio principal idêntico ao comando no grupo/DM alvo. Quando a
    execução é em grupo, cópias úteis são enviadas para a DM do solicitante por
    copy_message, sem reimplementar card, legenda ou mídia.
    """

    def __init__(self, *, bot: Bot, primary, dm_user_id: int | None, copy_to_dm: bool) -> None:
        self.bot = bot
        self._primary = primary
        self._dm_user_id = dm_user_id
        self._copy_to_dm = bool(copy_to_dm and dm_user_id and getattr(primary, "chat", None))
        self.chat = primary.chat
        self.message_id = primary.message_id
        self.from_user = None
        self.text = getattr(primary, "text", None)

    async def _copy_primary_to_dm(self) -> None:
        if not self._copy_to_dm or not self._dm_user_id:
            return
        try:
            if int(self.chat.id) == int(self._dm_user_id):
                return
        except Exception:
            return
        try:
            await self.bot.copy_message(
                chat_id=self._dm_user_id,
                from_chat_id=self.chat.id,
                message_id=self.message_id,
            )
        except Exception:
            logger.debug("WEB_MUSIC_COPY_TO_DM_FAILED chat=%s message=%s user=%s", getattr(self.chat, "id", None), self.message_id, self._dm_user_id, exc_info=True)

    async def edit_text(self, text: str, **kwargs):
        edited = await self._primary.edit_text(text, **kwargs)
        if not _looks_transient_text(text):
            try:
                await self.bot.send_message(chat_id=self._dm_user_id, text=text, **kwargs) if self._copy_to_dm and self._dm_user_id else None
            except Exception:
                logger.debug("WEB_MUSIC_EDIT_COPY_TO_DM_FAILED user=%s", self._dm_user_id, exc_info=True)
        if edited is not None:
            self._primary = edited
            self.chat = edited.chat
            self.message_id = edited.message_id
        return self


    @property
    def photo(self):
        return getattr(self._primary, "photo", None)

    @property
    def video(self):
        return getattr(self._primary, "video", None)

    @property
    def caption(self):
        return getattr(self._primary, "caption", None)

    async def edit_caption(self, caption: str | None = None, **kwargs):
        edited = await self._primary.edit_caption(caption=caption, **kwargs)
        if edited is not None:
            self._primary = edited
            self.chat = edited.chat
            self.message_id = edited.message_id
        if caption and not _looks_transient_text(caption):
            await self._copy_primary_to_dm()
        return self

    async def edit_reply_markup(self, **kwargs):
        try:
            edited = await self._primary.edit_reply_markup(**kwargs)
            if edited is not None:
                self._primary = edited
                self.chat = edited.chat
                self.message_id = edited.message_id
        except Exception:
            logger.debug("WEB_MUSIC_EDIT_REPLY_MARKUP_FAILED", exc_info=True)
        return self

    async def answer(self, text: str, **kwargs):
        sent = await self.bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
        wrapped = _WebSentMessage(bot=self.bot, primary=sent, dm_user_id=self._dm_user_id, copy_to_dm=self._copy_to_dm)
        if not _looks_transient_text(text):
            await wrapped._copy_primary_to_dm()
        return wrapped

    async def answer_photo(self, photo, **kwargs):
        sent = await self.bot.send_photo(chat_id=self.chat.id, photo=photo, **kwargs)
        wrapped = _WebSentMessage(bot=self.bot, primary=sent, dm_user_id=self._dm_user_id, copy_to_dm=self._copy_to_dm)
        await wrapped._copy_primary_to_dm()
        return wrapped

    async def answer_video(self, video, **kwargs):
        sent = await self.bot.send_video(chat_id=self.chat.id, video=video, **kwargs)
        wrapped = _WebSentMessage(bot=self.bot, primary=sent, dm_user_id=self._dm_user_id, copy_to_dm=self._copy_to_dm)
        await wrapped._copy_primary_to_dm()
        return wrapped


class _WebCommandMessage:
    def __init__(
        self,
        *,
        bot: Bot,
        chat_id: int,
        chat_title: str | None,
        chat_type: str,
        user_id: int,
        user_name: str,
        text: str,
        copy_to_dm: bool,
    ) -> None:
        self.bot = bot
        self.chat = _WebMusicChat(chat_id, chat_title, chat_type)
        self.from_user = _WebMusicUser(user_id, user_name)
        self.text = text
        self.message_id = 0
        self._copy_to_dm = copy_to_dm

    async def answer(self, text: str, **kwargs):
        sent = await self.bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
        wrapped = _WebSentMessage(
            bot=self.bot,
            primary=sent,
            dm_user_id=self.from_user.id,
            copy_to_dm=self._copy_to_dm,
        )
        if not _looks_transient_text(text):
            await wrapped._copy_primary_to_dm()
        return wrapped

    async def answer_photo(self, photo, **kwargs):
        sent = await self.bot.send_photo(chat_id=self.chat.id, photo=photo, **kwargs)
        wrapped = _WebSentMessage(
            bot=self.bot,
            primary=sent,
            dm_user_id=self.from_user.id,
            copy_to_dm=self._copy_to_dm,
        )
        await wrapped._copy_primary_to_dm()
        return wrapped

    async def answer_video(self, video, **kwargs):
        sent = await self.bot.send_video(chat_id=self.chat.id, video=video, **kwargs)
        wrapped = _WebSentMessage(
            bot=self.bot,
            primary=sent,
            dm_user_id=self.from_user.id,
            copy_to_dm=self._copy_to_dm,
        )
        await wrapped._copy_primary_to_dm()
        return wrapped


_WEB_BG_TASKS: set[asyncio.Task] = set()


def _spawn_web_task(coro) -> None:
    task = asyncio.create_task(coro)
    _WEB_BG_TASKS.add(task)
    task.add_done_callback(_WEB_BG_TASKS.discard)


async def _resolve_group(bot: Bot, requester_id: int, group_ref: str | int | None) -> tuple[int, str]:
    target_chat_id = _group_ref_to_chat_id(group_ref)
    if not await _is_active_member(bot, target_chat_id, requester_id):
        raise MusicCommandError("not_group_member", "Você não está mais nesse grupo.", status_code=403)
    try:
        chat = await bot.get_chat(target_chat_id)
        group_title = _normalize_optional_text(getattr(chat, "title", None)) or str(target_chat_id)
    except Exception:
        group_title = str(target_chat_id)
    return target_chat_id, group_title


_GROUP_COMMANDS = {"weekfm", "monthfm", "tcanvas", "tly", "tnow", "songcharts"}
_DM_COMMANDS = {"albnow", "radiofm", "playing", "tly"}


async def _run_group_command_task(
    bot: Bot,
    *,
    command: str,
    requester_id: int,
    requester_name: str,
    target_chat_id: int,
    group_title: str,
    period: str | None,
) -> None:
    try:
        if command == "songcharts":
            await _execute_songcharts_web(
                bot=bot,
                requester_id=requester_id,
                target_chat_id=target_chat_id,
                group_title=group_title,
                period=period,
            )
        else:
            message = _WebCommandMessage(
                bot=bot,
                chat_id=target_chat_id,
                chat_title=group_title,
                chat_type="supergroup",
                user_id=requester_id,
                user_name=requester_name,
                text=f"/{command}",
                copy_to_dm=True,
            )
            if command == "weekfm":
                from app.bot.weekfm import weekfm
                await weekfm(message)
            elif command == "monthfm":
                from app.bot.monthfm import monthfm
                await monthfm(message)
            elif command == "tcanvas":
                from app.bot.tcanvas import tcanvas
                await tcanvas(message)
            elif command == "tly":
                from app.bot.tly import tly
                await tly(message)
            elif command == "tnow":
                from app.bot.tnow import tnow
                await tnow(message)
            elif command == "tstory":
                from app.bot.tstory import tstory
                await tstory(message)
            else:
                raise MusicCommandError("command_not_supported", "Comando musical não suportado nesta etapa.", status_code=400)
        try:
            await bot.send_message(
                chat_id=requester_id,
                text=f"✓ /{html.escape(command)} enviado para <b>{html.escape(group_title)}</b>.",
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("WEB_MUSIC_COMMAND_CONFIRM_FAILED user=%s command=%s", requester_id, command, exc_info=True)
    except Exception:
        logger.exception("WEB_MUSIC_GROUP_COMMAND_TASK_FAILED command=%s user=%s chat=%s", command, requester_id, target_chat_id)
        try:
            await bot.send_message(
                chat_id=requester_id,
                text=f"Não consegui executar /{html.escape(command)} em <b>{html.escape(group_title)}</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def _execute_songcharts_web(
    *,
    bot: Bot,
    requester_id: int,
    target_chat_id: int,
    group_title: str,
    period: str | None,
) -> None:
    from app.bot.songcharts import _members_in_chat
    from app.services.lastfm import lastfm_service
    from app.services.lastfm_group import lastfm_group_service
    from app.services.monthfm_card import render_monthfm_card
    from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_EXTRACT

    period_kind = "month" if str(period or "").lower().startswith("m") else "week"
    label = "mês" if period_kind == "month" else "semana"
    status = await bot.send_message(
        target_chat_id,
        f"Gerando ranking do {label} de <b>{html.escape(group_title)}</b>...",
        parse_mode="HTML",
    )
    profiles = await lastfm_service.get_all_profiles()
    members = await _members_in_chat(bot, target_chat_id, profiles)
    try:
        result = await lastfm_group_service.build_group_capsule(
            chat_title=group_title,
            members=members,
            period_kind=period_kind,
        )
    except Exception:
        logger.exception("WEB_SONGCHARTS_BUILD_FAILED chat=%s", target_chat_id)
        try:
            await status.edit_text("Não consegui montar o ranking agora. Tente em alguns instantes.")
        except Exception:
            pass
        return
    card_bytes = await render_monthfm_card(result.card_data) if result.card_data else None
    period_value = ""
    if result.card_data is not None and result.card_data.period_value:
        period_value = result.card_data.period_value.lower()
    caption = f"Top 10 de {html.escape(group_title)}" + (
        f" · {html.escape(period_value)}" if period_value else ""
    )
    if card_bytes:
        sent = await bot.send_photo(
            chat_id=target_chat_id,
            photo=BufferedInputFile(card_bytes, filename="songcharts.jpg"),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        sent = await bot.send_message(
            chat_id=target_chat_id,
            text=result.text,
            parse_mode="HTML",
        )
    await _react_to_own_card(bot, sent.chat.id, sent.message_id, _CARD_EMOJI_EXTRACT)
    try:
        await bot.copy_message(chat_id=requester_id, from_chat_id=sent.chat.id, message_id=sent.message_id)
    except Exception:
        logger.debug("WEB_SONGCHARTS_COPY_DM_FAILED user=%s", requester_id, exc_info=True)


async def _run_universal_tnow_task(
    bot: Bot,
    *,
    requester_id: int,
) -> None:
    """Build and send the global live mosaic to the code owner DM only.

    The source is the same music base used by /tnow: every user_id found in
    spotify_tokens or lastfm_profiles. No group is used and nothing is posted
    publicly.
    """
    if not is_code_owner(requester_id):
        logger.info("WEB_UNIVERSAL_TNOW_BLOCKED_NON_OWNER | user_id=%s", requester_id)
        return

    from app.bot.tnow import _gather_entries
    from app.services.tnow_card import render_tnow_card
    from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_TNOW

    status = None
    try:
        status = await bot.send_message(
            requester_id,
            "Gerando mosaico universal com todos os usuários musicais importados...",
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("WEB_UNIVERSAL_TNOW_STATUS_DM_FAILED user=%s", requester_id, exc_info=True)

    try:
        entries = await _gather_entries(bot)
    except Exception:
        logger.exception("WEB_UNIVERSAL_TNOW_BUILD_FAILED user=%s", requester_id)
        try:
            if status is not None:
                await status.edit_text("Não consegui montar o mosaico universal agora. Tente em alguns instantes.")
            else:
                await bot.send_message(requester_id, "Não consegui montar o mosaico universal agora. Tente em alguns instantes.")
        except Exception:
            pass
        return

    try:
        if not entries:
            message = (
                "Nenhum usuário musical importado está com música tocando agora.\n"
                "Base usada: spotify_tokens ∪ lastfm_profiles."
            )
            if status is not None:
                await status.edit_text(message)
            else:
                await bot.send_message(requester_id, message)
            return

        card_bytes = await render_tnow_card(entries)
        caption = f"♫ <b>mosaico universal</b> • {len(entries)} pessoa{'s' if len(entries) != 1 else ''}"
        if card_bytes:
            sent = await bot.send_photo(
                chat_id=requester_id,
                photo=BufferedInputFile(card_bytes, filename="tnow-universal.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
        else:
            lines = [caption]
            for entry in entries:
                lines.append(
                    f"• <b>{html.escape(entry.display_name)}</b> — "
                    f"{html.escape(entry.track_name)} <i>({html.escape(entry.artist)})</i>"
                )
            sent = await bot.send_message(chat_id=requester_id, text="\n".join(lines), parse_mode="HTML")
        try:
            await _react_to_own_card(bot, sent.chat.id, sent.message_id, _CARD_EMOJI_TNOW)
        except Exception:
            logger.debug("WEB_UNIVERSAL_TNOW_REACTION_FAILED user=%s", requester_id, exc_info=True)
        try:
            if status is not None:
                await status.edit_text("✓ Mosaico universal enviado aqui na sua DM.")
        except Exception:
            pass
    except Exception:
        logger.exception("WEB_UNIVERSAL_TNOW_SEND_FAILED user=%s", requester_id)
        try:
            if status is not None:
                await status.edit_text("Não consegui enviar o mosaico universal na sua DM.")
        except Exception:
            pass


async def execute_universal_tnow(
    bot: Bot,
    *,
    requester_id: int,
    requester_name: str,
) -> MusicCommandResult:
    """Accept a code-owner-only global mosaic request.

    A segunda validação aqui impede vazamento caso alguma rota futura chame
    diretamente este executor sem passar pelo filtro do Web App/DM.
    """
    if not is_code_owner(requester_id):
        logger.info("WEB_UNIVERSAL_TNOW_REJECTED_NON_OWNER | user_id=%s", requester_id)
        raise MusicCommandError(
            "code_owner_required",
            "Mosaico universal é exclusivo do dono do código.",
            status_code=403,
        )
    _spawn_web_task(_run_universal_tnow_task(bot, requester_id=requester_id))
    return MusicCommandResult(
        ok=True,
        code="accepted",
        message="Mosaico universal aceito. O resultado será enviado na sua DM.",
        group_title=None,
    )


async def _run_universal_songcharts_task(
    bot: Bot,
    *,
    requester_id: int,
    period: str | None,
) -> None:
    """Build and send the global musical chart to the requester DM.

    Universal charts are based on every valid row in lastfm_profiles. This is
    intentionally independent from /start and from group membership: imported
    Last.fm profiles are part of the global music base automatically.
    """
    from app.services.lastfm import lastfm_service
    from app.services.lastfm_group import lastfm_group_service
    from app.services.monthfm_card import render_monthfm_card
    from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_EXTRACT

    period_kind = "month" if str(period or "").lower().startswith("m") else "week"
    label = "mês" if period_kind == "month" else "semana"
    status = None
    try:
        status = await bot.send_message(
            requester_id,
            f"Gerando Songcharts universal do {label} com todos os Last.fm importados...",
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("WEB_UNIVERSAL_SONGCHARTS_STATUS_DM_FAILED user=%s", requester_id, exc_info=True)

    try:
        profiles = await lastfm_service.get_all_profiles()
        result = await lastfm_group_service.build_group_capsule(
            chat_title="Todos conectados",
            members=profiles,
            period_kind=period_kind,
        )
    except Exception:
        logger.exception("WEB_UNIVERSAL_SONGCHARTS_BUILD_FAILED user=%s", requester_id)
        try:
            if status is not None:
                await status.edit_text("Não consegui montar o Songcharts universal agora. Tente em alguns instantes.")
            else:
                await bot.send_message(requester_id, "Não consegui montar o Songcharts universal agora. Tente em alguns instantes.")
        except Exception:
            pass
        return

    card_bytes = await render_monthfm_card(result.card_data) if result.card_data else None
    period_value = ""
    if result.card_data is not None and result.card_data.period_value:
        period_value = result.card_data.period_value.lower()
    caption = "Top 10 universal" + (f" · {html.escape(period_value)}" if period_value else "")

    try:
        if card_bytes:
            sent = await bot.send_photo(
                chat_id=requester_id,
                photo=BufferedInputFile(card_bytes, filename="songcharts-universal.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
        else:
            sent = await bot.send_message(
                chat_id=requester_id,
                text=result.text,
                parse_mode="HTML",
            )
        try:
            await _react_to_own_card(bot, sent.chat.id, sent.message_id, _CARD_EMOJI_EXTRACT)
        except Exception:
            logger.debug("WEB_UNIVERSAL_SONGCHARTS_REACTION_FAILED user=%s", requester_id, exc_info=True)
        try:
            if status is not None:
                await status.edit_text("✓ Songcharts universal enviado aqui na sua DM.")
        except Exception:
            pass
    except Exception:
        logger.exception("WEB_UNIVERSAL_SONGCHARTS_SEND_FAILED user=%s", requester_id)
        try:
            if status is not None:
                await status.edit_text("Não consegui enviar o Songcharts universal na sua DM.")
        except Exception:
            pass


async def execute_universal_songcharts(
    bot: Bot,
    *,
    requester_id: int,
    requester_name: str,
    period: str | None = None,
) -> MusicCommandResult:
    """Accept a universal chart request from the web music interface.

    The chart source is every valid Last.fm profile in lastfm_profiles. The
    requester only needs a valid Telegram WebApp session to receive the DM; the
    chart itself includes imported musical users automatically.
    """
    period_kind = "month" if str(period or "").lower().startswith("m") else "week"
    _spawn_web_task(
        _run_universal_songcharts_task(
            bot,
            requester_id=requester_id,
            period=period_kind,
        )
    )
    return MusicCommandResult(
        ok=True,
        code="accepted",
        message="Songcharts universal aceito. O resultado será enviado na sua DM.",
        group_title=None,
    )


async def execute_group_music_command(
    bot: Bot,
    *,
    command: str,
    requester_id: int,
    requester_name: str,
    group_ref: str | int | None,
    period: str | None = None,
) -> MusicCommandResult:
    command_key = str(command or "").strip().lower().lstrip("/")
    if command_key == "nowp":
        return await execute_nowp_publish(
            bot,
            requester_id=requester_id,
            requester_name=requester_name,
            group_ref=group_ref,
        )
    if command_key not in _GROUP_COMMANDS:
        raise MusicCommandError("command_not_allowed", "Comando musical não permitido nesta tela.", status_code=403)
    target_chat_id, group_title = await _resolve_group(bot, requester_id, group_ref)
    _spawn_web_task(
        _run_group_command_task(
            bot,
            command=command_key,
            requester_id=requester_id,
            requester_name=requester_name,
            target_chat_id=target_chat_id,
            group_title=group_title,
            period=period,
        )
    )
    return MusicCommandResult(
        ok=True,
        code="accepted",
        group_title=group_title,
        message=f"/{command_key} enviado para {group_title}. O resultado também será copiado na sua DM.",
    )


async def _run_dm_command_task(
    bot: Bot,
    *,
    command: str,
    requester_id: int,
    requester_name: str,
) -> None:
    try:
        message = _WebCommandMessage(
            bot=bot,
            chat_id=requester_id,
            chat_title=None,
            chat_type="private",
            user_id=requester_id,
            user_name=requester_name,
            text=f"/{command}",
            copy_to_dm=False,
        )
        if command == "albnow":
            await _execute_albnow_dm(message)
        elif command == "radiofm":
            from types import SimpleNamespace
            from app.bot.radiofm import radiofm
            await radiofm(message, SimpleNamespace(args=""))
        elif command == "playing":
            from app.bot.telegram import _send_playing
            await _send_playing(message)
        elif command == "tly":
            from app.bot.tly import tly
            await tly(message)
        else:
            raise MusicCommandError("command_not_supported", "Comando de DM não suportado.", status_code=400)
    except Exception:
        logger.exception("WEB_MUSIC_DM_COMMAND_TASK_FAILED command=%s user=%s", command, requester_id)
        try:
            await bot.send_message(chat_id=requester_id, text=f"Não consegui executar /{html.escape(command)} agora.", parse_mode="HTML")
        except Exception:
            pass


async def _execute_albnow_dm(message) -> None:
    from app.services.connection_check import connect_hint_for, is_user_connected
    from app.bot.music_extras import _format_albnow
    from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_DEFAULT
    if not message.from_user:
        return
    if not is_user_connected(message.from_user.id):
        await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
        return
    data = await music_service.get_current_or_last_played(message.from_user.id)
    if not data:
        await message.answer("Nada tocando agora.")
        return
    caption = _format_albnow(message.from_user.full_name, message.from_user.id, data)
    cover = data.get("album_image_url") or data.get("cover_url")
    if cover:
        sent = await _send_cached_cover_or_text(
            message.bot,
            message.chat.id,
            track_id=str(data.get("track_id") or "").strip() or None,
            cover=str(cover),
            caption=caption,
            filename="albnow-cover.jpg",
        )
    else:
        sent = await message.answer(caption, parse_mode="HTML")
    await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, _CARD_EMOJI_DEFAULT)


async def execute_dm_music_command(
    bot: Bot,
    *,
    command: str,
    requester_id: int,
    requester_name: str,
) -> MusicCommandResult:
    command_key = str(command or "").strip().lower().lstrip("/")
    if command_key not in _DM_COMMANDS:
        raise MusicCommandError("command_not_allowed", "Comando de DM não permitido nesta tela.", status_code=403)
    _spawn_web_task(
        _run_dm_command_task(
            bot,
            command=command_key,
            requester_id=requester_id,
            requester_name=requester_name,
        )
    )
    return MusicCommandResult(
        ok=True,
        code="accepted",
        message=f"/{command_key} enviado na sua DM.",
    )


async def execute_story_music_command(
    bot: Bot,
    *,
    requester_id: int,
    requester_name: str,
    target: str | None,
    group_ref: str | int | None = None,
) -> MusicCommandResult:
    target_key = str(target or "dm").strip().lower()
    if target_key == "group":
        target_chat_id, group_title = await _resolve_group(bot, requester_id, group_ref)
        chat_type = "supergroup"
        copy_to_dm = True
        message_text = f"/tstory enviado para {group_title}. O resultado também será copiado na sua DM."
    else:
        target_chat_id = requester_id
        group_title = None
        chat_type = "private"
        copy_to_dm = False
        message_text = "/tstory enviado na sua DM."
    _spawn_web_task(
        _run_group_command_task(
            bot,
            command="tstory",
            requester_id=requester_id,
            requester_name=requester_name,
            target_chat_id=target_chat_id,
            group_title=group_title or "DM",
            period=None,
        ) if target_key == "group" else _run_dm_tstory_task(
            bot,
            requester_id=requester_id,
            requester_name=requester_name,
        )
    )
    return MusicCommandResult(ok=True, code="accepted", group_title=group_title, message=message_text)


async def _run_dm_tstory_task(bot: Bot, *, requester_id: int, requester_name: str) -> None:
    try:
        message = _WebCommandMessage(
            bot=bot,
            chat_id=requester_id,
            chat_title=None,
            chat_type="private",
            user_id=requester_id,
            user_name=requester_name,
            text="/tstory",
            copy_to_dm=False,
        )
        from app.bot.tstory import tstory
        await tstory(message)
    except Exception:
        logger.exception("WEB_TSTORY_DM_TASK_FAILED user=%s", requester_id)
        try:
            await bot.send_message(chat_id=requester_id, text="Não consegui executar /tstory agora.")
        except Exception:
            pass


async def _resolve_preview_user_plays(user_id: int, track: dict[str, Any]) -> tuple[int, str]:
    """Resolve o contador exibido no card principal do Web App.

    Fonte preferida: Last.fm `track.getInfo` com `userplaycount`, porque
    representa quantas vezes aquele usuário ouviu aquela faixa no histórico
    real do Last.fm. Para usuários apenas Spotify, cai para o contador local
    do bot por usuário/faixa. A prévia não registra nova play; ela só mostra
    o que já existe.
    """
    track_name = _normalize_optional_text(track.get("track_name"))
    artist = _normalize_optional_text(track.get("artist"))
    if artist and track_name:
        try:
            lastfm_count = await lastfm_service.get_user_track_playcount(user_id, artist, track_name)
        except Exception:
            logger.exception("WEB_PREVIEW_LASTFM_PLAYCOUNT_FAILED user=%s artist=%s track=%s", user_id, artist, track_name)
        else:
            if lastfm_count is not None:
                return int(lastfm_count), "lastfm"

    track_id = _normalize_optional_text(track.get("track_id"))
    if track_id:
        try:
            return await likes_service.get_user_play_count(user_id, track_id), "local"
        except Exception:
            logger.exception("WEB_PREVIEW_LOCAL_PLAYCOUNT_FAILED user=%s track_id=%s", user_id, track_id)
    return 0, "none"


async def current_track_preview(user_id: int) -> dict[str, Any]:
    if not is_user_connected(user_id):
        return {
            "available": False,
            "code": "not_connected",
            "message": "Conecte Last.fm ou Spotify para ver sua música atual.",
        }
    track = await music_service.get_current_or_last_played(user_id)
    if not track:
        return {
            "available": False,
            "code": "no_track",
            "message": "Nada tocando agora.",
        }
    user_plays, plays_source = await _resolve_preview_user_plays(user_id, track)
    return {
        "available": True,
        "track_name": str(track.get("track_name") or ""),
        "artist": str(track.get("artist") or ""),
        "spotify_url": str(track.get("spotify_url") or track.get("track_url") or ""),
        "cover_url": str(track.get("album_image_url") or track.get("cover_url") or ""),
        "user_plays": user_plays,
        "plays_source": plays_source,
    }
