from __future__ import annotations

import html
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineQuery,
    InlineQueryResultPhoto,
    Message,
    MessageReactionUpdated,
    ChatJoinRequest,
    ReactionTypeEmoji,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot.intent import detect_intent
from app.config import settings
from app.config.settings import LASTFM_API_KEY
from app.services.connection_check import connect_hint_for, is_user_connected
from app.services.lastfm import lastfm_service
from app.services.lastfm_capsule import lastfm_capsule_service
from app.services.lyrics import lyrics_service
from app.services.likes import likes_service
from app.services.music import music_service
from app.services.reactions import reactions_service
from app.services.spotify import spotify_service
from app.equalizador.mesa import (
    ACTION_SPECS,
    MesaError,
    MesaNotFoundError,
    executar_ajuste,
    mesa_error_public_detail,
    parse_telegram_message_link,
    register_alvo_ref,
    register_mensagem_ref,
    resolve_alvo_manual,
)
from app.equalizador.entradas import register_join_request_from_update
from app.equalizador.avancado import register_sender_chat_ref, register_topic_ref
from app.equalizador.identity import make_ui_ref, public_tme_url
from app.equalizador.maestro import (
    MaestroError,
    executar_modo_silencio,
    executar_modo_silencio_desativar,
    executar_transmissao,
    maestro_error_public_detail,
)
from app.equalizador.permissions import canal_is_allowed
from app.equalizador.hardening import mesa_operation_lock
from app.equalizador.multimidia import (
    MultimediaError,
    attach_telegram_message_to_session,
    extract_multimedia_session_ref,
    mark_session_waiting,
)

logger = logging.getLogger(__name__)



bot_dispatcher: Dispatcher = Dispatcher()


# Sprint 9 (#8): IDs públicos de Message Effects (Premium / Bot API 7.7+).
# Telegram só aplica em chats privados; em grupos é silenciosamente
# ignorado. Wrap em try/except no caller pra cair pra send normal se
# o ID for inválido pra esse user/região (ex: Premium-only effects).
_EFFECT_FIRE = "5104841245755180586"      # 🔥
_EFFECT_PARTY = "5046509860389126442"     # 🎉
_EFFECT_THUMBS_UP = "5107584321108051014"  # 👍


# Sprint 10: emojis pra bot reagir nos próprios cards de música.
# Telegram restringe reactions de bots não-Premium à lista oficial
# (👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 ⚡ 💯 🏆 ❤‍🔥 etc) —
# 🎵 e 🎶 NÃO entram. 🔥 é o melhor proxy "musical/energético"; ❤
# marca milestone a cada 5 plays Last.fm.
_CARD_EMOJI_DEFAULT = "🔥"
_CARD_EMOJI_LOVED = "❤"
_CARD_EMOJI_EXTRACT = "🏆"  # extratos visuais: /myself, /weekfm, /monthfm, /songcharts
_CARD_EMOJI_TNOW = "🔥"      # mosaico /tnow (energia do grupo)
_LOVED_PLAYS_THRESHOLD = 5


def _pick_card_emoji(total_plays: int, plays_source: str) -> str | None:
    """Decide emoji do bot pro card quando reactions estiverem habilitadas.

    Fase 114: por segurança, o sistema de LED/reaction tracking fica
    desligado por padrão. Não remove tabelas nem código histórico; apenas
    impede novas reactions automáticas.
    """
    if not settings.TR4_MUSIC_REACTIONS_ENABLED:
        return None
    if (
        plays_source == "lastfm"
        and total_plays > 0
        and total_plays % _LOVED_PLAYS_THRESHOLD == 0
    ):
        return _CARD_EMOJI_LOVED
    return _CARD_EMOJI_DEFAULT


async def _react_to_own_card(bot, chat_id: int, message_id: int, emoji: str | None) -> None:
    """Bot reage no card apenas quando o recurso estiver habilitado."""
    if not settings.TR4_MUSIC_REACTIONS_ENABLED or not emoji:
        return
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        logger.debug(
            "OWN_CARD_REACT_FAILED chat=%s msg=%s emoji=%s",
            chat_id, message_id, emoji, exc_info=True,
        )



async def _answer_with_effect(message: Message, text: str, effect_id: str, **kwargs) -> Message:
    """Sprint 9 (#8): tenta enviar com message_effect_id; cai pra send normal em falha.

    Effects só funcionam em DM. Em grupo o Telegram costuma ignorar
    silenciosamente, mas algumas versões rejeitam — try/except garante
    que o user sempre recebe a mensagem.
    """
    if message.chat.type == "private":
        try:
            return await message.answer(text, message_effect_id=effect_id, **kwargs)
        except Exception:
            logger.debug("EFFECT_SEND_FAILED effect_id=%s", effect_id, exc_info=True)
    return await message.answer(text, **kwargs)


def _track_label(track: dict) -> tuple[str, str, str, str | None]:
    track_name = html.escape(str(track.get("track_name") or ""))
    artist = html.escape(str(track.get("artist") or ""))
    url = html.escape(str(track.get("spotify_url") or ""), quote=True)
    cover = track.get("album_image_url")
    return track_name, artist, url, str(cover) if cover else None


def _user_mention(message: Message) -> str:
    if not message.from_user:
        return "Usuário"
    display_name = html.escape(message.from_user.full_name or "Usuário")
    contato_url = public_tme_url(getattr(message.from_user, "username", None))
    if contato_url:
        return f'<a href="{html.escape(contato_url, quote=True)}">{display_name}</a>'
    return display_name


# Negrito unicode (Mathematical Bold) pro nome de exibição no /tly. Telegram
# já bolda com <b>, mas o /tly quer o nome em fonte negrito-unicode distinta
# (ex.: 𝐏𝐈) renderizada inline no texto. Mapeia só A-Z/a-z/0-9 — caracteres
# sem equivalente nesse bloco unicode (acentos PT-BR como ã/é, espaço,
# pontuação) ficam na forma original.
_BOLD_UPPER_OFFSET = 0x1D400 - ord("A")
_BOLD_LOWER_OFFSET = 0x1D41A - ord("a")
_BOLD_DIGIT_OFFSET = 0x1D7CE - ord("0")


def _equalizador_safe_label(value: object, *, fallback: str = "Membro") -> str:
    text = str(value or "").strip().replace("@", "")
    return text[:120] or fallback


async def _remember_equalizador_message(message: Message) -> None:
    """Register message/member aliases for the Equalizador UI without affecting handlers."""
    try:
        allowed_palcos = settings.equalizador_allowed_palco_ids()
        if not settings.TR4_EQUALIZADOR_ENABLED or int(message.chat.id) not in allowed_palcos:
            return
        alias_secret = settings.equalizador_alias_secret()
        text_value = (message.text or message.caption or "").strip()
        resumo = text_value[:140] if text_value else "Mensagem"
        register_mensagem_ref(
            chat_id=int(message.chat.id),
            message_id=int(message.message_id),
            resumo_publico=resumo,
            alias_secret=alias_secret,
            message_unix_time=int(message.date.timestamp()) if message.date else None,
            autor_user_id=int(message.from_user.id) if message.from_user and not message.from_user.is_bot else None,
            autor_nome_publico=_equalizador_safe_label(message.from_user.full_name) if message.from_user and not message.from_user.is_bot else None,
            autor_username=message.from_user.username if message.from_user and not message.from_user.is_bot else None,
        )
        sender_chat = getattr(message, "sender_chat", None)
        if sender_chat is not None and getattr(sender_chat, "id", None):
            register_sender_chat_ref(
                chat_id=int(message.chat.id),
                sender_chat_id=int(sender_chat.id),
                titulo_publico=_equalizador_safe_label(getattr(sender_chat, "title", None), fallback="Canal remetente"),
                username=getattr(sender_chat, "username", None),
                alias_secret=alias_secret,
            )
        thread_id = getattr(message, "message_thread_id", None)
        if thread_id:
            register_topic_ref(
                chat_id=int(message.chat.id),
                message_thread_id=int(thread_id),
                nome_publico=f"Tópico {int(thread_id)}",
                alias_secret=alias_secret,
            )
        if message.from_user and not message.from_user.is_bot:
            register_alvo_ref(
                chat_id=int(message.chat.id),
                user_id=int(message.from_user.id),
                nome_publico=_equalizador_safe_label(message.from_user.full_name),
                username=message.from_user.username,
                alias_secret=alias_secret,
            )
        for member in getattr(message, "new_chat_members", None) or []:
            if member and not getattr(member, "is_bot", False):
                register_alvo_ref(
                    chat_id=int(message.chat.id),
                    user_id=int(member.id),
                    nome_publico=_equalizador_safe_label(member.full_name),
                    username=getattr(member, "username", None),
                    alias_secret=alias_secret,
                )
        replied = getattr(message, "reply_to_message", None)
        if replied is not None:
            register_mensagem_ref(
                chat_id=int(message.chat.id),
                message_id=int(replied.message_id),
                resumo_publico=(replied.text or replied.caption or "Mensagem respondida")[:140],
                alias_secret=alias_secret,
                message_unix_time=int(replied.date.timestamp()) if replied.date else None,
                autor_user_id=int(replied.from_user.id) if replied.from_user and not replied.from_user.is_bot else None,
                autor_nome_publico=_equalizador_safe_label(replied.from_user.full_name) if replied.from_user and not replied.from_user.is_bot else None,
                autor_username=replied.from_user.username if replied.from_user and not replied.from_user.is_bot else None,
            )
            if replied.from_user and not replied.from_user.is_bot:
                register_alvo_ref(
                    chat_id=int(message.chat.id),
                    user_id=int(replied.from_user.id),
                    nome_publico=_equalizador_safe_label(replied.from_user.full_name),
                    username=replied.from_user.username,
                    alias_secret=alias_secret,
                )
    except Exception:
        logger.debug("EQUALIZADOR_CAPTURE_FAILED", exc_info=True)


class EqualizadorCaptureMiddleware(BaseMiddleware):
    """Capture message/member aliases for the Equalizador without consuming updates.

    Aiogram middlewares must call the downstream handler to keep normal bot
    routing intact. The capture is best-effort and cannot block music handlers.
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        await _remember_equalizador_message(event)
        return await handler(event, data)



async def _remember_equalizador_join_request(event: ChatJoinRequest) -> None:
    """Register pending join requests for the Equalizador entry queue."""
    try:
        allowed_palcos = settings.equalizador_allowed_palco_ids()
        if not settings.TR4_EQUALIZADOR_ENABLED or int(event.chat.id) not in allowed_palcos:
            return
        invite_link = None
        raw_invite = getattr(event, "invite_link", None)
        if raw_invite is not None:
            invite_link = getattr(raw_invite, "invite_link", None)
        user = event.from_user
        register_join_request_from_update(
            chat_id=int(event.chat.id),
            user={
                "id": int(user.id),
                "first_name": getattr(user, "first_name", None),
                "last_name": getattr(user, "last_name", None),
                "username": getattr(user, "username", None),
            },
            bio=getattr(event, "bio", None),
            invite_link=invite_link,
            alias_secret=settings.equalizador_alias_secret(),
        )
    except Exception:
        logger.debug("EQUALIZADOR_JOIN_REQUEST_CAPTURE_FAILED", exc_info=True)

def _bold_unicode(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(ord(ch) + _BOLD_UPPER_OFFSET))
        elif "a" <= ch <= "z":
            out.append(chr(ord(ch) + _BOLD_LOWER_OFFSET))
        elif "0" <= ch <= "9":
            out.append(chr(ord(ch) + _BOLD_DIGIT_OFFSET))
        else:
            out.append(ch)
    return "".join(out)


async def _resolve_play_button_count(user_id: int, track_id: str, artist: str | None, track_name: str | None) -> tuple[int, str]:
    if artist and track_name:
        lastfm_count = await lastfm_service.get_user_track_playcount(user_id, artist, track_name)
        if lastfm_count is not None:
            return lastfm_count, "lastfm"
    return await likes_service.get_track_play_count(track_id), "local"


async def build_playing_payload_for_user(
    user_id: int, display_name_raw: str, track: dict, username: str | None = None
) -> tuple[str, str, str | None, None, str] | None:
    """Variante que aceita user_id/display_name explícitos.

    Usada por /nowp (envio remoto via callback, onde `message.from_user` seria
    o bot e não o user real). Mesma lógica/saída de `build_playing_payload`.

    Registra a play ANTES de resolver counts/likes pra que o counter exibido
    no botão reflita o estado atualizado (inclui a play recém-registrada).
    Em caso de falha no envio posterior, ficaria um "phantom play" no DB —
    trade-off aceito porque o oposto (counter N-1 visível) é pior pro user.
    """
    track_id = str(track.get("track_id") or "").strip()
    if not track_id:
        return None

    track_name_raw = str(track.get("track_name") or "").strip()
    artist_raw = str(track.get("artist") or "").strip()
    try:
        await likes_service.register_play(user_id, track_id, track_name=track_name_raw, artist_name=artist_raw)
    except Exception:
        logger.exception("REGISTER_PLAY_FAILED user=%s track=%s", user_id, track_id)

    total_plays, plays_source = await _resolve_play_button_count(user_id, track_id, artist_raw, track_name_raw)

    display_name = html.escape((display_name_raw or "").strip() or (f"@{username}" if username else "Usuário"))
    user_link = public_tme_url(username)
    track_name, artist, track_url, cover = _track_label(track)
    track_part = f'<a href="{track_url}"><b>{track_name}</b></a>' if track_url else f'<b>{track_name}</b>'
    user_part = f'<a href="{html.escape(user_link, quote=True)}">{display_name}</a>' if user_link else display_name
    caption = (
        f"{user_part} · ♫ <code>{total_plays}</code>\n\n"
        f"{track_part} — <i>{artist}</i>"
    )
    card_emoji = _pick_card_emoji(total_plays, plays_source)
    return track_id, caption, cover, None, card_emoji


async def build_playing_payload(
    message: Message, track: dict
) -> tuple[str, str, str | None, None, str] | None:
    """Registra o play e monta (track_id, caption HTML, cover_url, keyboard).

    Side effect: chama `likes_service.register_play`. Retorna `None` se faltar
    `from_user` ou `track_id`. Reaproveitado por /playing e /tcanvas pra
    garantir mesma legenda + mesmos botões.
    """
    if not message.from_user:
        return None
    return await build_playing_payload_for_user(
        message.from_user.id,
        message.from_user.full_name or "Usuário",
        track,
        message.from_user.username,
    )


async def build_tly_payload(
    message: Message, track: dict, lyric_snippet: str | None
) -> tuple[str, str, str | None, str] | None:
    """Monta o payload do /tly: cabeçalho enxuto + quote expansível da letra.

    Mesma infra do /playing (registra a play e resolve o contador ♫), mas a
    legenda é diferente: nome de exibição em negrito unicode · ♫ N · faixa —
    artista, seguido de um `<blockquote expandable>` com `lyric_snippet`. Sem
    a linha de ♥ likes. Quando `lyric_snippet` é None/vazio, sai só o
    cabeçalho. Retorna (track_id, caption HTML, cover_url, card_emoji) ou None
    se faltar `from_user`/`track_id`.

    Side effect: chama `likes_service.register_play` (igual ao /tcanvas).
    """
    if not message.from_user:
        return None
    user_id = message.from_user.id
    display_name_raw = message.from_user.full_name or "Usuário"

    track_id = str(track.get("track_id") or "").strip()
    if not track_id:
        return None

    track_name_raw = str(track.get("track_name") or "").strip()
    artist_raw = str(track.get("artist") or "").strip()
    try:
        await likes_service.register_play(user_id, track_id, track_name=track_name_raw, artist_name=artist_raw)
    except Exception:
        logger.exception("REGISTER_PLAY_FAILED user=%s track=%s", user_id, track_id)

    total_plays, plays_source = await _resolve_play_button_count(user_id, track_id, artist_raw, track_name_raw)

    track_name, artist, track_url, cover = _track_label(track)
    track_part = f'<a href="{track_url}">{track_name}</a>' if track_url else track_name
    name_part = html.escape(_bold_unicode(display_name_raw))
    header = f"{name_part} · ♫ {total_plays} · {track_part} — <i>{artist}</i>"
    if lyric_snippet:
        caption = f"{header}\n<blockquote expandable>{html.escape(lyric_snippet)}</blockquote>"
    else:
        caption = header

    card_emoji = _pick_card_emoji(total_plays, plays_source)
    return track_id, caption, cover, card_emoji


async def _safe_delete(message: Message) -> None:
    """Tenta deletar a mensagem. Falha em silêncio se bot não tem permissão
    (Forbidden/BadRequest). Usado pra limpar comandos/gatilhos em grupos."""
    try:
        await message.delete()
    except Exception:
        logger.debug("SAFE_DELETE_FAILED chat=%s msg=%s", message.chat.id, message.message_id, exc_info=True)


def _hidden_equalizador_allowed(message: Message) -> bool:
    return bool(
        message.chat.type == "private"
        and message.from_user
        and int(message.from_user.id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET
    )


def _hidden_palco_id(value: str) -> int | None:
    raw = str(value or "").strip().lstrip("@")
    if raw.lstrip("-").isdigit():
        chat_id = int(raw)
        return chat_id if chat_id in settings.equalizador_allowed_palco_ids() else None
    aliases = {str(name).casefold(): int(chat_id) for name, chat_id in settings.group_aliases().items()}
    chat_id = aliases.get(raw.casefold())
    return chat_id if chat_id in settings.equalizador_allowed_palco_ids() else None


def _hidden_palco_label(chat_id: int) -> str:
    return settings.group_alias_for_chat(chat_id) or "palco"


async def _hidden_equalizador_denied(message: Message) -> None:
    await message.answer("Acesso indisponível.")


def _hidden_operator_ref(message: Message) -> str:
    if not message.from_user:
        return "usr_oculto"
    return make_ui_ref("usr", int(message.from_user.id), settings.equalizador_alias_secret())


def _hidden_palco_dict(chat_id: int) -> dict[str, object]:
    return {
        "telegram_chat_id": int(chat_id),
        "ui_ref": make_ui_ref("grp", int(chat_id), settings.equalizador_alias_secret()),
        "titulo": _hidden_palco_label(int(chat_id)),
    }


def _hidden_has_canal(message: Message, chat_id: int, canal_codigo: str) -> bool:
    if not message.from_user:
        return False
    return canal_is_allowed(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=int(message.from_user.id),
        chat_id=int(chat_id),
        canal_codigo=canal_codigo,
        is_maestro=True,
    )


async def _hidden_require_canal(message: Message, chat_id: int, canal_codigo: str) -> bool:
    if _hidden_has_canal(message, chat_id, canal_codigo):
        return True
    await message.answer("Canal indisponível para este palco.")
    return False


def _hidden_message_ref_from_input(chat_id: int, raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if value.startswith("msg_"):
        return value
    parsed_chat_id, message_id = parse_telegram_message_link(link=value, aliases=settings.group_aliases())
    if int(parsed_chat_id) != int(chat_id):
        raise MesaNotFoundError("mensagem_indisponivel")
    return register_mensagem_ref(
        chat_id=int(chat_id),
        message_id=int(message_id),
        resumo_publico="Mensagem marcada por comando oculto",
        alias_secret=settings.equalizador_alias_secret(),
    )


async def _hidden_target_ref_from_input(chat_id: int, raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if value.startswith("usr_"):
        return value
    alvo = await resolve_alvo_manual(
        palco_id=int(chat_id),
        identificador=value,
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        alias_secret=settings.equalizador_alias_secret(),
    )
    return str(alvo["alvo_ref"])


async def _hidden_run_mesa_action(message: Message, chat_id: int, ajuste: str, payload: dict[str, object]) -> None:
    spec = ACTION_SPECS.get(ajuste)
    if spec is None:
        await message.answer("Ajuste indisponível.")
        return
    if not await _hidden_require_canal(message, chat_id, spec.canal_codigo):
        return
    ator_ref = _hidden_operator_ref(message)
    palco = _hidden_palco_dict(chat_id)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:{ajuste}:hidden"):
            result = await executar_ajuste(
                ajuste=ajuste,
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        lines = [f"Ajuste concluído: {ajuste}", f"Palco: {_hidden_palco_label(chat_id)}"]
        if result.get("convite"):
            lines.append(str(result["convite"]))
        if result.get("msg_ref"):
            lines.append(f"Mensagem: {result['msg_ref']}")
        if result.get("membro") and isinstance(result["membro"], dict):
            membro = result["membro"]
            lines.append(f"Alvo: {membro.get('alvo_ref', 'alvo')}")
        await message.answer("\n".join(lines), disable_web_page_preview=True)
    except MesaError as exc:
        await message.answer(mesa_error_public_detail(exc))
    except Exception:
        logger.debug("EQUALIZADOR_HIDDEN_ACTION_FAILED", exc_info=True)
        await message.answer("Ajuste não concluído.")


async def _hidden_run_maestro_action(message: Message, chat_id: int, ajuste: str, payload: dict[str, object]) -> None:
    if not await _hidden_require_canal(message, chat_id, ajuste):
        return
    ator_ref = _hidden_operator_ref(message)
    palco = _hidden_palco_dict(chat_id)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:{ajuste}:hidden"):
            if ajuste == "transmissao.enviar":
                result = await executar_transmissao(
                    palco=palco, ator_ref=ator_ref, payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret(),
                )
            elif ajuste == "silencio.ativar":
                result = await executar_modo_silencio(
                    palco=palco, ator_ref=ator_ref, payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret(),
                )
            elif ajuste == "silencio.desativar":
                result = await executar_modo_silencio_desativar(
                    palco=palco, ator_ref=ator_ref, payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret(),
                )
            else:
                await message.answer("Ajuste indisponível.")
                return
        await message.answer(f"Ajuste concluído: {ajuste}\nPalco: {_hidden_palco_label(chat_id)}")
    except MesaError as exc:
        await message.answer(mesa_error_public_detail(exc))
    except MaestroError as exc:
        await message.answer(maestro_error_public_detail(exc))
    except Exception:
        logger.debug("EQUALIZADOR_HIDDEN_MAESTRO_FAILED", exc_info=True)
        await message.answer("Ajuste crítico não concluído.")


async def _hidden_message_action_command(message: Message, ajuste: str, usage: str) -> None:
    if not _hidden_equalizador_allowed(message):
        await _hidden_equalizador_denied(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(usage)
        return
    chat_id = _hidden_palco_id(parts[1])
    if chat_id is None:
        await message.answer("Palco indisponível.")
        return
    try:
        msg_ref = _hidden_message_ref_from_input(chat_id, parts[2])
    except MesaError as exc:
        await message.answer(mesa_error_public_detail(exc))
        return
    await _hidden_run_mesa_action(message, chat_id, ajuste, {"msg_ref": msg_ref})


async def _hidden_member_action_command(
    message: Message,
    ajuste: str,
    usage: str,
    *,
    allow_duration: bool = False,
) -> None:
    if not _hidden_equalizador_allowed(message):
        await _hidden_equalizador_denied(message)
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(usage)
        return
    chat_id = _hidden_palco_id(parts[1])
    if chat_id is None:
        await message.answer("Palco indisponível.")
        return
    try:
        alvo_ref = await _hidden_target_ref_from_input(chat_id, parts[2])
    except MesaError as exc:
        await message.answer(mesa_error_public_detail(exc))
        return
    payload: dict[str, object] = {"alvo_ref": alvo_ref}
    if allow_duration:
        minutes = 10
        if len(parts) >= 4:
            try:
                minutes = max(1, min(int(parts[3]), 60 * 24 * 7))
            except ValueError:
                await message.answer("Duração inválida. Use minutos em número.")
                return
        payload["duracao_segundos"] = minutes * 60
    if ajuste == "membros.remover":
        payload["revogar_mensagens"] = False
    await _hidden_run_mesa_action(message, chat_id, ajuste, payload)


async def _hidden_silencio_command(message: Message, ajuste: str, usage: str) -> None:
    if not _hidden_equalizador_allowed(message):
        await _hidden_equalizador_denied(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(usage)
        return
    chat_id = _hidden_palco_id(parts[1])
    if chat_id is None:
        await message.answer("Palco indisponível.")
        return
    await _hidden_run_maestro_action(message, chat_id, ajuste, {"confirmacao": parts[2].strip()})


async def _send_playing(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    if not is_user_connected(user_id):
        await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
        return

    # U3: em grupo, apaga o comando/gatilho pra não poluir a conversa.
    # O card da música vira a única mensagem visível (igual /nowp).
    is_group = message.chat.type in ("group", "supergroup")
    if is_group:
        await _safe_delete(message)

    # U1: feedback nativo "enviando foto..." enquanto resolve track + monta payload.
    try:
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass

    track = await music_service.get_current_or_last_played(user_id)
    if not track:
        await message.answer(
            "Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo.",
        )
        return

    payload = await build_playing_payload(message, track)
    if not payload:
        await message.answer("Erro ao identificar a música.")
        return
    track_id, caption, cover, keyboard, card_emoji = payload

    if cover:
        sent = await message.answer_photo(photo=cover, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    else:
        sent = await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)

    # Sprint 8: registra (chat_id, message_id) -> track pra que reactions
    # nativas dos users virem stats. Fire-and-forget interno (service
    # captura exceções), nunca quebra o envio do card.
    await reactions_service.register_card(
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        track_id=track_id,
        owner_user_id=user_id,
        track_name=str(track.get("track_name") or "").strip() or None,
        artist_name=str(track.get("artist") or "").strip() or None,
    )
    # Sprint 10: bot reage no próprio card (🔥 padrão, ❤ a cada 5 plays Last.fm).
    await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, card_emoji)



def _multimedia_message_payload(message: Message) -> dict[str, object] | None:
    caption = getattr(message, "caption", None) or ""
    text_value = getattr(message, "text", None) or caption or ""
    if getattr(message, "photo", None):
        photo = message.photo[-1]
        return {"media_kind": "photo", "file_id": photo.file_id, "file_unique_id": photo.file_unique_id, "texto": caption}
    if getattr(message, "video", None):
        video = message.video
        return {"media_kind": "video", "file_id": video.file_id, "file_unique_id": video.file_unique_id, "file_name": getattr(video, "file_name", "") or "video", "mime_type": getattr(video, "mime_type", "") or "video/mp4", "texto": caption}
    if getattr(message, "animation", None):
        animation = message.animation
        return {"media_kind": "animation", "file_id": animation.file_id, "file_unique_id": animation.file_unique_id, "file_name": getattr(animation, "file_name", "") or "animacao", "mime_type": getattr(animation, "mime_type", "") or "video/mp4", "texto": caption}
    if getattr(message, "document", None):
        document = message.document
        return {"media_kind": "document", "file_id": document.file_id, "file_unique_id": document.file_unique_id, "file_name": getattr(document, "file_name", "") or "documento", "mime_type": getattr(document, "mime_type", "") or "application/octet-stream", "texto": caption}
    if getattr(message, "audio", None):
        audio = message.audio
        return {"media_kind": "audio", "file_id": audio.file_id, "file_unique_id": audio.file_unique_id, "file_name": getattr(audio, "file_name", "") or "audio", "mime_type": getattr(audio, "mime_type", "") or "audio/mpeg", "texto": caption}
    if getattr(message, "voice", None):
        voice = message.voice
        return {"media_kind": "voice", "file_id": voice.file_id, "file_unique_id": voice.file_unique_id, "mime_type": getattr(voice, "mime_type", "") or "audio/ogg", "texto": caption}
    if text_value.strip():
        return {"media_kind": "text", "texto": text_value.strip()}
    return None


def _multimedia_return_keyboard() -> InlineKeyboardMarkup | None:
    base_url = getattr(settings, "BASE_URL", "").rstrip("/")
    if not base_url or "localhost" in base_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Voltar ao painel", url=f"{base_url}/equalizador")]])

def _register_handlers(dp: Dispatcher) -> None:
    if not getattr(dp, "_equalizador_capture_middleware_registered", False):
        dp.message.outer_middleware(EqualizadorCaptureMiddleware())
        setattr(dp, "_equalizador_capture_middleware_registered", True)

    @dp.message(F.web_app_data)
    async def public_player_web_app_data(message: Message) -> None:
        raw = getattr(getattr(message, "web_app_data", None), "data", "") or ""
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict) or payload.get("type") != "public_command_copy":
            return
        command = str(payload.get("command") or "").strip().lower().lstrip("/")
        group_ref = str(payload.get("group_ref") or "").strip()
        allowed = {"playing", "weekfm", "monthfm", "songcharts", "nowp", "tcanvas", "tstory", "tly", "tnow"}
        if command not in allowed:
            await message.answer("Comando do Mini App indisponível nesta conversa.")
            return
        # Fase 138.5: cada botão do Mini App executa o comando real já existente.
        # O Mini App não monta resultado nem texto de cópia; ele só envia o nome
        # do comando e, quando necessário, o grupo escolhido.
        if command == "playing":
            await _send_playing(message)
            return
        if command == "weekfm":
            from app.bot.weekfm import weekfm as _weekfm_handler
            await _weekfm_handler(message)
            return
        if command == "monthfm":
            from app.bot.monthfm import monthfm as _monthfm_handler
            await _monthfm_handler(message)
            return
        if command == "nowp":
            from app.bot.music_extras import _list_common_groups, _nowp_groups_keyboard
            if not message.from_user or not message.bot:
                return
            if not is_user_connected(message.from_user.id):
                await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
                return
            status_msg = await message.answer("Procurando grupos em comum...")
            common = await _list_common_groups(message.bot, message.from_user.id)
            if not common:
                await status_msg.edit_text("Nenhum grupo em comum encontrado.")
                return
            await status_msg.edit_text(
                "♫ Pra qual grupo enviar sua música atual?",
                reply_markup=_nowp_groups_keyboard(message.from_user.id, common),
            )
            return
        if command == "songcharts":
            if not message.from_user or not message.bot:
                return
            if group_ref:
                from app.bot.music_groups import list_groups
                from app.bot.songcharts import _is_chat_admin, _members_in_chat, _render_and_send
                def _miniapp_group_ref(chat_id: int) -> str:
                    return make_ui_ref("grp", int(chat_id), settings.equalizador_alias_secret())
                group = None
                for item in list_groups(80):
                    try:
                        chat_id = int(item.get("chat_id"))
                    except Exception:
                        continue
                    if _miniapp_group_ref(chat_id) == group_ref:
                        group = item
                        break
                if not group:
                    await message.answer("Escolha um grupo válido no Mini App antes de executar /songcharts.")
                    return
                chat_id = int(group["chat_id"])
                if not await _is_chat_admin(message.bot, chat_id, message.from_user.id):
                    await message.answer("♫ /songcharts está liberado só pras administradoras do grupo.")
                    return
                status = await message.answer(f"Gerando ranking de {html.escape(str(group.get('title') or 'grupo'))}...")
                profiles = await lastfm_service.get_all_profiles()
                members = await _members_in_chat(message.bot, chat_id, profiles)
                await _render_and_send(
                    bot=message.bot,
                    target_chat_id=message.chat.id,
                    chat_title=str(group.get("title") or "grupo"),
                    members=members,
                    period_kind="week",
                    status_message=status,
                    pin=False,
                )
                return
            from app.bot.songcharts import songcharts as _songcharts_handler
            await _songcharts_handler(message)
            return
        if command == "tcanvas":
            from app.bot.tcanvas import tcanvas as _tcanvas_handler
            await _tcanvas_handler(message)
            return
        if command == "tstory":
            from app.bot.tstory import tstory as _tstory_handler
            await _tstory_handler(message)
            return
        if command == "tly":
            from app.bot.tly import tly as _tly_handler
            await _tly_handler(message)
            return
        if command == "tnow":
            from app.bot.tnow import tnow as _tnow_handler
            await _tnow_handler(message)
            return

    @dp.message(Command("start"))
    async def start(message: Message) -> None:
        # Sprint 9 (#3): deep links via /start <payload>.
        # Payloads suportados:
        #   - lastfm_<username> → tenta conectar Last.fm direto
        #     (URL: t.me/<bot>?start=lastfm_romastefale)
        #   - connect           → mostra fluxo de conexão (Last.fm + Spotify)
        #   - help              → atalho pra /help
        # Sem payload (ou payload desconhecido) → greeting padrão.
        # Validação: payload é alfanumérico + underscore, max 64 chars
        # (limite do próprio start_parameter do Telegram).
        parts = (message.text or "").split(maxsplit=1)
        payload = parts[1].strip() if len(parts) >= 2 else ""

        if payload.startswith("cmd_") and message.from_user:
            cmd = payload[len("cmd_"):].strip().lower()
            if cmd == "playing":
                await _send_playing(message)
                return
            if cmd == "myself":
                from app.bot.myself import myself
                await myself(message)
                return
            if cmd == "weekfm":
                from app.bot.weekfm import weekfm
                await weekfm(message)
                return
            if cmd == "monthfm":
                from app.bot.monthfm import monthfm
                await monthfm(message)
                return
            if cmd == "songcharts":
                await message.answer("Use /songcharts no grupo onde deseja ver o ranking.")
                return
            if cmd == "nowp":
                await message.answer("Abra o Mini App, escolha um grupo e toque em Publicar atual.")
                return

        if payload.startswith("mm_") and message.from_user:
            try:
                sessao = mark_session_waiting(session_ref=payload, telegram_user_id=int(message.from_user.id))
                await message.answer(
                    f"Sessão {payload}. Envie aqui no privado o texto, foto, vídeo, áudio ou documento. Depois volte ao Web App e confirme a publicação.",
                    reply_markup=ForceReply(selective=True),
                )
                return
            except MultimediaError:
                await message.answer("Sessão multimídia indisponível ou pertencente a outro usuário.")
                return

        if payload.startswith("cmd_") and message.from_user:
            command = payload[len("cmd_"):].strip().lower().lstrip("/")
            if command == "playing":
                await _send_playing(message)
                return
            if command == "myself":
                from app.bot.myself import myself as _myself_handler
                await _myself_handler(message)
                return
            if command == "weekfm":
                from app.bot.weekfm import weekfm as _weekfm_handler
                await _weekfm_handler(message)
                return
            if command == "monthfm":
                from app.bot.monthfm import monthfm as _monthfm_handler
                await _monthfm_handler(message)
                return
            if command == "nowp":
                await message.answer("Abra o Mini App, escolha um grupo e toque em Publicar atual.")
                return
            if command == "songcharts":
                await message.answer("O ranking usa /songcharts dentro do grupo e respeita a regra de administrador.")
                return

        if payload.startswith("lastfm_") and message.from_user:
            raw_username = payload[len("lastfm_"):]
            mention = _user_mention(message)
            if not raw_username:
                await message.answer(
                    f"{mention}, link inválido (faltou o username).",
                    parse_mode="HTML",
                )
                return
            try:
                username, previous = await lastfm_service.set_username(
                    message.from_user.id, raw_username
                )
            except ValueError:
                await message.answer(
                    f"{mention}, username Last.fm inválido: "
                    f"<code>{html.escape(raw_username)}</code>",
                    parse_mode="HTML",
                )
                return
            if previous and previous.lower() == username.lower():
                head = f"{mention}, Last.fm reconfirmado: <b>@{html.escape(username)}</b>."
            elif previous:
                head = (
                    f"{mention}, atualizei seu Last.fm de "
                    f"<b>@{html.escape(previous)}</b> pra <b>@{html.escape(username)}</b>."
                )
            else:
                head = f"{mention}, Last.fm conectado: <b>@{html.escape(username)}</b>."
            await _answer_with_effect(message, head, _EFFECT_FIRE, parse_mode="HTML")
            return

        if payload == "connect":
            await message.answer(
                "🎧 <b>Conectar suas contas no tigraoRADIO</b>\n\n"
                "<b>Last.fm</b> (obrigatório pra extratos):\n"
                "<code>/lastfm seu_username</code> (sem @)\n\n"
                "<b>Spotify</b> (opcional, fallback):\n"
                "<code>/login</code>\n\n"
                "Depois disso, <code>/playing</code> mostra o que você está ouvindo.",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        if payload == "help":
            # Redireciona pro mesmo conteúdo do /help.
            await help_command(message)  # type: ignore[name-defined]
            return

        # Sprint 9 (#8): greeting padrão ganha efeito 🎉 (DM only, fallback OK).
        await _answer_with_effect(
            message,
            "♫ ♥ <b>Bem-vindo ao tigraoRADIO</b>\n\n"
            "Conecte seu Last.fm e o bot acompanha o que você está ouvindo, "
            "gera extratos visuais e monta rankings do grupo.\n\n"
            "<b>Primeiro passo:</b> <code>/lastfm seu_username</code> (sem @)\n"
            "<b>Lista completa de comandos:</b> /help",
            _EFFECT_PARTY,
            parse_mode="HTML",
        )

    @dp.message(Command("mesa_ajuda"))
    async def equalizador_hidden_help(message: Message) -> None:
        if not _hidden_equalizador_allowed(message):
            await _hidden_equalizador_denied(message)
            return
        await message.answer(
            "<b>Mesa oculta</b>\n"
            "Uso somente no privado e somente Maestro.\n\n"
            "<code>/mesa_msg &lt;link_da_mensagem&gt;</code>\n"
            "<code>/mesa_alvo &lt;grupo&gt; &lt;username_ou_alvo_ref&gt;</code>\n"
            "<code>/mesa_apagar &lt;palco&gt; &lt;link_ou_msg_ref&gt;</code>\n"
            "<code>/mesa_fixar &lt;palco&gt; &lt;link_ou_msg_ref&gt;</code>\n"
            "<code>/mesa_desfixar &lt;palco&gt; &lt;link_ou_msg_ref&gt;</code>\n"
            "<code>/mesa_silenciar &lt;palco&gt; &lt;username_ou_alvo_ref&gt; [minutos]</code>\n"
            "<code>/mesa_liberar &lt;palco&gt; &lt;username_ou_alvo_ref&gt;</code>\n"
            "<code>/mesa_remover &lt;palco&gt; &lt;username_ou_alvo_ref&gt;</code>\n"
            "<code>/mesa_reintegrar &lt;palco&gt; &lt;username_ou_alvo_ref&gt;</code>\n"
            "<code>/mesa_convite &lt;palco&gt; [nome]</code>\n"
            "<code>/mesa_tx &lt;palco&gt; CONFIRMAR AJUSTE | texto</code>\n"
            "<code>/mesa_silencio &lt;palco&gt; CONFIRMAR AJUSTE</code>\n"
            "<code>/mesa_silencio_off &lt;palco&gt; CONFIRMAR AJUSTE</code>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    @dp.message(Command("mesa_msg"))
    async def equalizador_hidden_msg(message: Message) -> None:
        if not _hidden_equalizador_allowed(message):
            await _hidden_equalizador_denied(message)
            return
        link = (message.text or "").split(maxsplit=1)[1].strip() if len((message.text or "").split(maxsplit=1)) > 1 else ""
        if not link:
            await message.answer("Uso: /mesa_msg <link_da_mensagem>")
            return
        try:
            chat_id, message_id = parse_telegram_message_link(link=link, aliases=settings.group_aliases())
            if chat_id not in settings.equalizador_allowed_palco_ids():
                await message.answer("Palco do link não está autorizado no Equalizador.")
                return
            msg_ref = register_mensagem_ref(
                chat_id=chat_id,
                message_id=message_id,
                resumo_publico="Mensagem marcada por comando oculto",
                alias_secret=settings.equalizador_alias_secret(),
            )
            await message.answer(f"Mensagem marcada: {msg_ref}\nPalco: {_hidden_palco_label(chat_id)}")
        except MesaError as exc:
            await message.answer(mesa_error_public_detail(exc))

    @dp.message(Command("mesa_alvo"))
    async def equalizador_hidden_alvo(message: Message) -> None:
        if not _hidden_equalizador_allowed(message):
            await _hidden_equalizador_denied(message)
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("Uso: /mesa_alvo <grupo> <username_ou_alvo_ref>")
            return
        chat_id = _hidden_palco_id(parts[1])
        if chat_id is None:
            await message.answer("Palco indisponível.")
            return
        try:
            alvo_ref = await _hidden_target_ref_from_input(chat_id, parts[2])
            await message.answer(f"Alvo marcado: {alvo_ref}\nPalco: {_hidden_palco_label(chat_id)}")
        except MesaError as exc:
            await message.answer(mesa_error_public_detail(exc))

    @dp.message(Command("mesa_apagar"))
    async def equalizador_hidden_apagar(message: Message) -> None:
        await _hidden_message_action_command(message, "mensagens.apagar", "Uso: /mesa_apagar <palco> <link_ou_msg_ref>")

    @dp.message(Command("mesa_fixar"))
    async def equalizador_hidden_fixar(message: Message) -> None:
        await _hidden_message_action_command(message, "fixados.criar", "Uso: /mesa_fixar <palco> <link_ou_msg_ref>")

    @dp.message(Command("mesa_desfixar"))
    async def equalizador_hidden_desfixar(message: Message) -> None:
        await _hidden_message_action_command(message, "fixados.remover", "Uso: /mesa_desfixar <palco> <link_ou_msg_ref>")

    @dp.message(Command("mesa_silenciar"))
    async def equalizador_hidden_silenciar(message: Message) -> None:
        await _hidden_member_action_command(
            message,
            "membros.silenciar",
            "Uso: /mesa_silenciar <grupo> <username_ou_alvo_ref> [minutos]",
            allow_duration=True,
        )

    @dp.message(Command("mesa_liberar"))
    async def equalizador_hidden_liberar(message: Message) -> None:
        await _hidden_member_action_command(message, "membros.liberar", "Uso: /mesa_liberar <grupo> <username_ou_alvo_ref>")

    @dp.message(Command("mesa_remover"))
    async def equalizador_hidden_remover(message: Message) -> None:
        await _hidden_member_action_command(message, "membros.remover", "Uso: /mesa_remover <grupo> <username_ou_alvo_ref>")

    @dp.message(Command("mesa_reintegrar"))
    async def equalizador_hidden_reintegrar(message: Message) -> None:
        await _hidden_member_action_command(message, "membros.reintegrar", "Uso: /mesa_reintegrar <grupo> <username_ou_alvo_ref>")

    @dp.message(Command("mesa_convite"))
    async def equalizador_hidden_convite(message: Message) -> None:
        if not _hidden_equalizador_allowed(message):
            await _hidden_equalizador_denied(message)
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 2:
            await message.answer("Uso: /mesa_convite <palco> [nome]")
            return
        chat_id = _hidden_palco_id(parts[1])
        if chat_id is None:
            await message.answer("Palco indisponível.")
            return
        name = parts[2].strip() if len(parts) > 2 else "Equalizador"
        await _hidden_run_mesa_action(message, chat_id, "convites.criar", {"nome": name, "enviar_dm": False})

    @dp.message(Command("mesa_tx"))
    async def equalizador_hidden_tx(message: Message) -> None:
        if not _hidden_equalizador_allowed(message):
            await _hidden_equalizador_denied(message)
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or "|" not in parts[2]:
            await message.answer("Uso: /mesa_tx <palco> CONFIRMAR AJUSTE | texto")
            return
        chat_id = _hidden_palco_id(parts[1])
        if chat_id is None:
            await message.answer("Palco indisponível.")
            return
        confirmacao, texto = [chunk.strip() for chunk in parts[2].split("|", 1)]
        await _hidden_run_maestro_action(
            message,
            chat_id,
            "transmissao.enviar",
            {"confirmacao": confirmacao, "texto": texto, "sem_preview": True},
        )

    @dp.message(Command("mesa_silencio"))
    async def equalizador_hidden_silencio(message: Message) -> None:
        await _hidden_silencio_command(message, "silencio.ativar", "Uso: /mesa_silencio <palco> CONFIRMAR AJUSTE")

    @dp.message(Command("mesa_silencio_off"))
    async def equalizador_hidden_silencio_off(message: Message) -> None:
        await _hidden_silencio_command(message, "silencio.desativar", "Uso: /mesa_silencio_off <palco> CONFIRMAR AJUSTE")


    @dp.message(Command("help"))
    async def help_command(message: Message) -> None:
        # Sprint 10: effect FIRE em DM (toda vez), graceful fallback em grupo.
        await _answer_with_effect(
            message,
            "<b>COMANDOS</b>\n\n"
            "— TOCANDO AGORA —\n\n"
            "♫ /playing\n"
            "Mostra a música que VOCÊ está ouvindo agora (capa + nome + artista + álbum). "
            "Se nada estiver tocando, mostra a última registrada. Tem botões de like/dislike.\n\n"
            "◐ /albnow\n"
            "Foco no <b>álbum</b> da sua música atual: capa do álbum, nome, artista e ano. "
            "Útil quando você quer destacar o disco e não a faixa solta.\n\n"
            "▶ /tcanvas\n"
            "Pega o Spotify Canvas (aquele vídeo curto vertical em loop que toca no app do Spotify) "
            "da sua música atual e manda aqui. Se a faixa não tiver Canvas, cai automaticamente pra capa do álbum.\n\n"
            "◉ /tnow\n"
            "Mosaico ao vivo de quem está ouvindo o quê <b>neste grupo</b> agora.\n\n"
            "✈ /nowp\n"
            "Envia sua música atual (mesmo formato do /playing) pra um grupo onde "
            "você e o bot estão juntos, <b>sem precisar entrar no grupo</b>. "
            "Roda no privado, mostra a lista dos grupos em comum, você escolhe e o bot publica lá. "
            "Confirma no privado com o nome do grupo onde foi enviado.\n\n"
            "— EXTRATOS LAST.FM —\n\n"
            "★ /myself\n"
            "Porta de entrada do seu extrato pessoal. Abre um menu com dois botões: "
            "🟢 <b>Semanal</b>  |  🔴 <b>Mensal</b>. Gera um card visual com top artistas e músicas. "
            "Em grupo, só quem rodou o comando consegue clicar nos botões.\n\n"
            "— CONEXÃO (LAST.FM) —\n\n"
            "↻ /lastfm &lt;username&gt;\n"
            "Conecta seu perfil <b>público</b> do Last.fm ao bot (sem o @). "
            "Ex.: se sua URL é <code>last.fm/user/romastefale</code>, manda <code>/lastfm romastefale</code>. "
            "SEM ISSO você não aparece em /tnow nem usa /playing, /tcanvas, /myself. "
            "Sem argumento, mostra qual username está salvo.\n\n"
            "⨯ /lastfmoff\n"
            "Remove o vínculo do seu Last.fm com o bot.",
            _EFFECT_FIRE,
            parse_mode="HTML",
        )

    @dp.chat_join_request()
    async def equalizador_join_request(event: ChatJoinRequest) -> None:
        await _remember_equalizador_join_request(event)

    @dp.message(Command("login"))
    async def login(message: Message) -> None:
        if message.chat.type != "private":
            await message.answer(
                "🔒 Pra conectar suas contas, fala comigo no privado:\n"
                "1) <code>/login</code> — autoriza o Spotify\n"
                "2) <code>/lastfm seu_username</code> (sem o @) — conecta o Last.fm\n\n"
                "Sem isso você não aparece no /tnow nem usa /monthfm, /weekfm e cia.",
                parse_mode="HTML",
            )
            return
        if not message.from_user:
            return
        auth_url = spotify_service.build_auth_url(message.from_user.id)
        await message.answer(
            "🎧 <b>Conectando suas contas no tigraoRADIO</b>\n\n"
            f"1) <b>Spotify</b> — abre este link e autoriza:\n{auth_url}\n\n"
            "2) <b>Last.fm</b> — manda aqui:\n"
            "<code>/lastfm seu_username</code>  (sem o @)\n\n"
            "Só depois desses dois passos seu nome entra no /tnow e os comandos "
            "/monthfm, /weekfm, /playing funcionam pra você.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    @dp.message(Command("logout"))
    async def logout(message: Message) -> None:
        if not message.from_user:
            return
        await spotify_service.clear_user_session(message.from_user.id)
        await message.answer("Spotify desconectado.")

    @dp.message(Command("lastfm"))
    async def lastfm(message: Message) -> None:
        if not message.from_user:
            return
        mention = _user_mention(message)
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            current = await lastfm_service.get_username(message.from_user.id)
            if current:
                await message.answer(
                    f"{mention}, seu Last.fm salvo é <b>@{html.escape(current)}</b>.\n"
                    "Pra trocar: <code>/lastfm outro_username</code> (sem o @).\n"
                    "Pra desconectar: /lastfmoff",
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    f"{mention}, você ainda não conectou um Last.fm.\n\n"
                    "🎧 <b>Como conectar:</b>\n"
                    "1) Abre seu perfil no Last.fm: https://www.last.fm/\n"
                    "2) Copia só o <b>username</b> (o que vem depois de /user/, <b>sem o @</b>)\n"
                    "3) Manda aqui: <code>/lastfm seu_username</code>\n\n"
                    "Exemplo: se sua URL é <code>last.fm/user/romastefale</code>, "
                    "manda <code>/lastfm romastefale</code>.\n\n"
                    "Sem isso você não aparece no /tnow nem usa /monthfm e /weekfm.",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return
        try:
            username, previous = await lastfm_service.set_username(message.from_user.id, parts[1])
        except ValueError:
            await message.answer(f"{mention}, username Last.fm inválido.", parse_mode="HTML")
            return
        if previous and previous.lower() == username.lower():
            head = f"{mention}, Last.fm reconfirmado: <b>@{html.escape(username)}</b>."
        elif previous:
            head = (
                f"{mention}, atualizei seu Last.fm de <b>@{html.escape(previous)}</b> "
                f"pra <b>@{html.escape(username)}</b>."
            )
        else:
            head = f"{mention}, Last.fm conectado: <b>@{html.escape(username)}</b>."
        if not LASTFM_API_KEY:
            await message.answer(
                f"{head}\n\n"
                "A leitura do Last.fm precisa da variável LASTFM_API_KEY no Railway. "
                "Enquanto ela não existir, o bot continua usando Spotify como fallback.",
                parse_mode="HTML",
            )
            return
        # Sprint 9 (#8): conexão bem-sucedida ganha efeito 🔥 (DM only, fallback OK).
        await _answer_with_effect(message, head, _EFFECT_FIRE, parse_mode="HTML")

    @dp.message(Command("lastfmoff"))
    async def lastfmoff(message: Message) -> None:
        if not message.from_user:
            return
        mention = _user_mention(message)
        removed = await lastfm_service.clear_username(message.from_user.id)
        # Sprint 10: effect THUMBS_UP em DM (toda vez), graceful em grupo.
        await _answer_with_effect(
            message,
            f"{mention}, Last.fm removido." if removed else f"{mention}, nenhum Last.fm estava conectado.",
            _EFFECT_THUMBS_UP,
            parse_mode="HTML",
        )

    @dp.message(Command("playing"))
    async def playing(message: Message) -> None:
        await _send_playing(message)

    # /myself e /songcharts foram movidos pra `app/bot/myself.py` e
    # `app/bot/songcharts.py`. Os novos comandos usam Last.fm (em vez de
    # likes locais) e renderizam o mesmo card visual dos /weekfm e
    # /monthfm. O ranking de grupo (/songcharts) agrega todos os
    # membros conectados e fixa a mensagem.

    @dp.callback_query(F.data.startswith("plays:"))
    async def plays_callback(query: CallbackQuery) -> None:
        if not query.from_user or not query.data:
            return
        parts = query.data.split(":", 3)
        if len(parts) == 4:
            try:
                owner_user_id = int(parts[1])
            except ValueError:
                owner_user_id = query.from_user.id
            plays_source = parts[2]
            track_id = parts[3]
        elif len(parts) == 3:
            try:
                owner_user_id = int(parts[1])
            except ValueError:
                owner_user_id = query.from_user.id
            plays_source = "local"
            track_id = parts[2]
        else:
            owner_user_id = query.from_user.id
            plays_source = "local"
            track_id = query.data.split(":", 1)[1]
        count = await likes_service.get_user_play_count(owner_user_id, track_id)
        if plays_source == "lastfm":
            await query.answer("O número azul é o total do Last.fm.\nPelo bot: " + str(count) + " vez" + ("" if count == 1 else "es") + ".", show_alert=True)
        else:
            await query.answer(f"O dono já ouviu {count} vez" + ("" if count == 1 else "es") + " pelo bot.", show_alert=True)

    @dp.callback_query(F.data.startswith("like:"))
    async def like_callback(query: CallbackQuery) -> None:
        # Sprint 8: botão ♥ likes foi removido — substituído por reactions
        # nativas. Stub silencioso pra mensagens ANTIGAS (cards postados
        # antes do deploy) que ainda têm o botão pendurado. Sem isso, o
        # clique falharia com "callback expired" e o user veria erro.
        await query.answer("Agora curtir é só reagir na mensagem 👀")

    @dp.message_reaction()
    async def on_message_reaction(event: MessageReactionUpdated) -> None:
        if not settings.TR4_MUSIC_REACTIONS_ENABLED:
            return
        """Sprint 8: tracking de reactions nos cards /playing.

        Telegram envia este update toda vez que um user adiciona/remove
        reaction numa mensagem em grupo onde o bot é admin. Se a mensagem
        for um card trackado (existe em card_messages), grava o diff em
        track_reactions. Caso contrário, ignora silenciosamente.
        """
        if not event.user:
            return  # reaction anônima (rara) ou de canal — ignora
        old_emojis = [
            r.emoji for r in (event.old_reaction or [])
            if hasattr(r, "emoji") and getattr(r, "emoji", None)
        ]
        new_emojis = [
            r.emoji for r in (event.new_reaction or [])
            if hasattr(r, "emoji") and getattr(r, "emoji", None)
        ]
        try:
            await reactions_service.apply_reaction_change(
                chat_id=event.chat.id,
                message_id=event.message_id,
                user_id=event.user.id,
                old_emojis=old_emojis,
                new_emojis=new_emojis,
            )
        except Exception:
            logger.exception(
                "MESSAGE_REACTION_FAILED chat=%s msg=%s user=%s",
                event.chat.id, event.message_id, event.user.id,
            )

    # Inline público. Query vazia (ou "playing") -> card da música tocando
    # como 1ª opção. Query com termo -> busca por termo (mesmo motor do /radiofm).
    def _is_x9_inline_format(query: InlineQuery) -> bool:
        parts = (query.query or "").strip().split()
        if len(parts) != 2:
            return False
        return all(p.lstrip("-").isdigit() for p in parts)

    async def _answer_playing(query: InlineQuery) -> None:
        track = await music_service.get_current_or_last_played(query.from_user.id)
        if not track:
            await query.answer([], cache_time=1, is_personal=True)
            return
        track_name, artist, track_url, cover = _track_label(track)
        if not cover:
            await query.answer([], cache_time=1, is_personal=True)
            return
        who = html.escape(query.from_user.full_name or "Usuário")
        track_part = f'<a href="{track_url}">{track_name}</a>' if track_url else track_name
        caption = f"<i>{who} · {track_part} - {artist}</i>"
        result = InlineQueryResultPhoto(
            id=str(uuid.uuid4()),
            photo_url=cover,
            thumbnail_url=cover,
            caption=caption,
            parse_mode="HTML",
        )
        await query.answer([result], cache_time=2, is_personal=True)

    @dp.inline_query(lambda q: not _is_x9_inline_format(q))
    async def inline_public(query: InlineQuery) -> None:
        raw = (query.query or "").strip()
        if not raw or raw.lower() == "playing":
            await _answer_playing(query)
            return

        from app.services.track_search import search_tracks

        hits = await search_tracks(raw, limit=10)
        results: list[InlineQueryResultPhoto] = []
        for hit in hits:
            if not hit.cover_big:
                continue
            caption = f"<b>{html.escape(hit.title)}</b> - <i>{html.escape(hit.artist)}</i>"
            results.append(
                InlineQueryResultPhoto(
                    id=str(uuid.uuid4()),
                    photo_url=hit.cover_big,
                    thumbnail_url=hit.cover_thumb or hit.cover_big,
                    title=hit.title,
                    description=hit.artist,
                    caption=caption,
                    parse_mode="HTML",
                )
            )
        await query.answer(results, cache_time=5, is_personal=True)


    @dp.message(
        StateFilter(None),
        F.chat.type == "private",
        (F.photo | F.video | F.document | F.audio | F.voice),
    )
    async def equalizador_multimedia_private_media(message: Message) -> None:
        if not message.from_user:
            return
        payload_data = _multimedia_message_payload(message)
        hint = extract_multimedia_session_ref(getattr(getattr(message, "reply_to_message", None), "text", "") or getattr(getattr(message, "reply_to_message", None), "caption", ""))
        if not payload_data:
            return
        try:
            sessao = attach_telegram_message_to_session(telegram_user_id=int(message.from_user.id), message_data=payload_data, session_ref_hint=hint)
        except MultimediaError as exc:
            await message.answer(str(exc)[:160] or "Conteúdo multimídia não aceito.")
            return
        if not sessao:
            return
        keyboard = _multimedia_return_keyboard()
        await message.answer("Conteúdo recebido. Volte ao Web App para confirmar a publicação no grupo.", reply_markup=keyboard)

    @dp.message(
        StateFilter(None),
        F.chat.type == "private",
        F.reply_to_message,
        F.text,
        ~F.text.startswith("/"),
    )
    async def equalizador_multimedia_private_text_reply(message: Message) -> None:
        if not message.from_user:
            return
        payload_data = _multimedia_message_payload(message)
        hint = extract_multimedia_session_ref(getattr(getattr(message, "reply_to_message", None), "text", "") or getattr(getattr(message, "reply_to_message", None), "caption", ""))
        if not payload_data:
            return
        try:
            sessao = attach_telegram_message_to_session(telegram_user_id=int(message.from_user.id), message_data=payload_data, session_ref_hint=hint)
        except MultimediaError as exc:
            await message.answer(str(exc)[:160] or "Texto não aceito.")
            return
        if not sessao:
            return
        keyboard = _multimedia_return_keyboard()
        await message.answer("Texto recebido. Volte ao Web App para confirmar a publicação no grupo.", reply_markup=keyboard)


    @dp.message(
        StateFilter(None),
        F.chat.type == "private",
        F.text,
        ~F.text.startswith("/"),
    )
    async def equalizador_multimedia_private_text_active_session(message: Message) -> object:
        if not message.from_user:
            return None  # phase133: aiogram handler fallback sem NameError
        try:
            active = active_session_for_user(telegram_user_id=int(message.from_user.id))
        except Exception:
            active = None
        if not active:
            return None  # phase133: aiogram handler fallback sem NameError
        payload_data = _multimedia_message_payload(message)
        hint = extract_multimedia_session_ref(getattr(getattr(message, "reply_to_message", None), "text", "") or getattr(getattr(message, "reply_to_message", None), "caption", ""))
        if not payload_data:
            return None  # phase133: aiogram handler fallback sem NameError
        try:
            sessao = attach_telegram_message_to_session(telegram_user_id=int(message.from_user.id), message_data=payload_data, session_ref_hint=hint)
        except MultimediaError as exc:
            await message.answer(str(exc)[:160] or "Texto não aceito.")
            return None
        if not sessao:
            return None  # phase133: aiogram handler fallback sem NameError
        keyboard = _multimedia_return_keyboard()
        await message.answer("Texto recebido. Volte ao Web App para confirmar a publicação no grupo.", reply_markup=keyboard)
        return None

    # IMPORTANTE: o filtro `~F.text.startswith("/")` impede que este handler
    # consuma comandos. Sem isso, qualquer texto começando com "/" (ex.:
    # /weekfm, /monthfm em sub-routers) bateria neste handler primeiro, o
    # `return` cedo devolveria None ao observer (que NÃO é UNHANDLED em
    # aiogram3), e a propagação para sub-routers seria abortada.
    # StateFilter(None) também evita interceptar texto durante FSM.
    # Music-only: não há painéis privados de moderação. O guard permanece
    # defensivo e retorna False se módulos legados não existirem.
    def _owner_dialog_active(message: Message) -> bool:
        # Music-only build: não há painéis privados com estado de espera.
        return False

    @dp.message(
        StateFilter(None),
        F.text,
        ~F.text.startswith("/"),
        lambda m: not _owner_dialog_active(m),
    )
    async def text_aliases(message: Message) -> None:
        text = message.text or ""
        if detect_intent(text) == "play":
            # U3: _send_playing já deleta a mensagem em grupo (gatilho some
            # antes do card aparecer). Em DM, mantém o texto do user.
            await _send_playing(message)


async def shutdown_telegram_bot() -> None:
    shutdown_steps = (
        ("spotify", spotify_service.shutdown),
        ("lastfm", lastfm_service.shutdown),
        ("lastfm_capsule", lastfm_capsule_service.shutdown),
        ("lyrics", lyrics_service.shutdown),
    )
    for service_name, shutdown in shutdown_steps:
        try:
            await shutdown()
        except Exception:
            logger.exception("SERVICE_SHUTDOWN_FAILED service=%s", service_name)
