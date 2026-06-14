"""/radiofm — busca uma música por termo livre e envia o card avulso.

Fluxo: `/radiofm <termo>` busca candidatos e mostra uma lista de botões
(título - artista). `/radiofm` sem termo pergunta qual música buscar e aceita
uma resposta direta ao prompt ou a próxima mensagem do mesmo autor no mesmo
chat. Ao escolher, o bot envia o card final sem apagar mensagens do grupo.

Sem contador de play/like e sem registro de reações (diferente de /playing e
/tcanvas). ZERO emojis na interface.
"""
from __future__ import annotations

import html
import logging
import time
import uuid
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.services.track_search import TrackHit, search_tracks

logger = logging.getLogger(__name__)
router = Router(name="radiofm")

_MAX_RESULTS = 8
_CACHE_BOUND = 500
_PENDING_TTL = 300.0  # 5min: tempo de sobra pra escolher; depois expira.
_PROMPT_TTL = 180.0  # 3min pra responder a pergunta do /radiofm sem termo.


@dataclass
class _Pending:
    hits: list[TrackHit]
    user_id: int
    user_name: str
    command_chat_id: int
    command_msg_id: int
    ts: float = field(default_factory=time.monotonic)


@dataclass
class _PromptPending:
    user_id: int
    chat_id: int
    command_msg_id: int
    prompt_msg_id: int
    ts: float = field(default_factory=time.monotonic)


# token -> resultados pendentes de escolha. Bound simples (clear ao estourar).
_pending: dict[str, _Pending] = {}
# (chat_id, user_id) -> pergunta pendente do /radiofm sem termo.
_prompt_pending: dict[tuple[int, int], _PromptPending] = {}


def _purge_expired() -> None:
    now = time.monotonic()
    stale = [k for k, v in _pending.items() if now - v.ts > _PENDING_TTL]
    for k in stale:
        _pending.pop(k, None)
    prompt_stale = [k for k, v in _prompt_pending.items() if now - v.ts > _PROMPT_TTL]
    for k in prompt_stale:
        _prompt_pending.pop(k, None)


def _user_anchor(user_id: int, user_name: str) -> str:
    safe_name = html.escape(user_name or "Usuário")
    user_link = f"tg://user?id={int(user_id)}"
    return f'<b><a href="{html.escape(user_link, quote=True)}">{safe_name}</a></b>'


def _card_caption(hit: TrackHit, *, user_id: int, user_name: str, spotify_url: str | None) -> str:
    title = html.escape(hit.title)
    artist = html.escape(hit.artist)
    safe_url = html.escape(spotify_url or "", quote=True)
    track_part = f'<a href="{safe_url}">{title}</a>' if safe_url else title
    return f"{_user_anchor(user_id, user_name)}\n\n♫ <b>{track_part}</b> — <i>{artist}</i>"


def _question_key(message: Message) -> tuple[int, int] | None:
    if not message.from_user:
        return None
    return int(message.chat.id), int(message.from_user.id)


def _is_radiofm_prompt_answer(message: Message) -> bool:
    key = _question_key(message)
    if key is None:
        return False
    _purge_expired()
    pending = _prompt_pending.get(key)
    if pending is None:
        return False
    reply = getattr(message, "reply_to_message", None)
    reply_id = getattr(reply, "message_id", None)
    if reply_id == pending.prompt_msg_id:
        return True
    try:
        return int(message.message_id) > int(pending.prompt_msg_id)
    except Exception:
        return False


async def _resolve_spotify_output(hit: TrackHit) -> tuple[str | None, str | None]:
    """Resolve URL/capa do Spotify para o resultado escolhido.

    O Deezer continua sendo usado só como motor de busca pública. O card final
    prioriza link e capa do Spotify para manter o mesmo padrão das demais
    interações musicais.
    """
    try:
        from app.services.spotify import spotify_service

        match = await spotify_service.search_track(hit.artist, hit.title)
    except Exception:
        logger.warning("RADIOFM_SPOTIFY_RESOLVE_FAILED track=%s", hit.track_id, exc_info=True)
        match = None
    if match:
        return match.get("url"), match.get("cover") or hit.cover_big
    return None, hit.cover_big


async def _present_radiofm_results(
    message: Message,
    *,
    term: str,
    requester_id: int,
    requester_name: str,
    command_msg_id: int,
) -> None:
    clean_term = (term or "").strip()
    if not clean_term:
        await message.answer("Manda o nome da música ou artista para buscar no RadioFM.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    hits = await search_tracks(clean_term, limit=_MAX_RESULTS)
    if not hits:
        await message.answer(f'Nada encontrado para "{html.escape(clean_term)}".')
        return

    token = uuid.uuid4().hex[:10]
    _purge_expired()
    if len(_pending) >= _CACHE_BOUND:
        _pending.clear()
    _pending[token] = _Pending(
        hits=hits,
        user_id=requester_id,
        user_name=requester_name or "Usuário",
        command_chat_id=message.chat.id,
        command_msg_id=command_msg_id,
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{h.title} - {h.artist}", callback_data=f"rfm:{token}:{i}")]
            for i, h in enumerate(hits)
        ]
    )
    await message.answer("Escolha a faixa:", reply_markup=keyboard)


@router.message(Command("radiofm"))
async def radiofm(message: Message, command: CommandObject) -> None:
    if not message.from_user or not message.bot:
        return
    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "radiofm"):
        return

    term = (command.args or "").strip()
    requester_id = int(message.from_user.id)
    requester_name = message.from_user.full_name or "Usuário"
    if not term:
        prompt = await message.answer(
            "Qual música você quer buscar no RadioFM?\n"
            "Responda esta mensagem ou envie o nome da música na sua próxima mensagem."
        )
        _purge_expired()
        _prompt_pending[(int(message.chat.id), requester_id)] = _PromptPending(
            user_id=requester_id,
            chat_id=int(message.chat.id),
            command_msg_id=int(message.message_id),
            prompt_msg_id=int(prompt.message_id),
        )
        return

    await _present_radiofm_results(
        message,
        term=term,
        requester_id=requester_id,
        requester_name=requester_name,
        command_msg_id=int(message.message_id),
    )


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"), _is_radiofm_prompt_answer)
async def radiofm_prompt_answer(message: Message) -> None:
    if not message.from_user:
        return
    key = _question_key(message)
    pending = _prompt_pending.pop(key, None) if key else None
    if pending is None:
        return
    await _present_radiofm_results(
        message,
        term=message.text or "",
        requester_id=int(message.from_user.id),
        requester_name=message.from_user.full_name or "Usuário",
        command_msg_id=pending.command_msg_id,
    )


@router.callback_query(F.data.startswith("rfm:"))
async def radiofm_pick(query: CallbackQuery) -> None:
    if not query.data or not query.message or not query.from_user or not query.bot:
        await query.answer()
        return

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, token, raw_idx = parts

    pending = _pending.get(token)
    if pending is None or (time.monotonic() - pending.ts) > _PENDING_TTL:
        _pending.pop(token, None)
        await query.answer("Essa busca expirou. Rode /radiofm de novo.", show_alert=True)
        return
    if query.from_user.id != pending.user_id:
        await query.answer("Essa busca é de outra pessoa. Rode /radiofm você também.", show_alert=True)
        return

    try:
        hit = pending.hits[int(raw_idx)]
    except (ValueError, IndexError):
        await query.answer()
        return

    # Claim atômico ANTES de qualquer await: elimina envio duplicado em
    # duplo-clique (o 2º callback acha o token já removido). asyncio é
    # single-thread, então get->validação->pop roda sem interleaving.
    if _pending.pop(token, None) is None:
        await query.answer()
        return

    await query.answer()

    bot = query.bot
    chat_id = query.message.chat.id
    spotify_url, cover_url = await _resolve_spotify_output(hit)
    caption = _card_caption(
        hit,
        user_id=pending.user_id,
        user_name=pending.user_name,
        spotify_url=spotify_url,
    )

    sent = None
    if cover_url:
        try:
            sent = await bot.send_photo(
                chat_id, photo=cover_url, caption=caption, parse_mode="HTML"
            )
        except Exception:
            logger.warning("RADIOFM_SEND_PHOTO_FAILED track=%s", hit.track_id, exc_info=True)
    if sent is None:
        await bot.send_message(
            chat_id, caption, parse_mode="HTML", disable_web_page_preview=True
        )

    # Music-only clean: não apaga comando/lista no grupo.
