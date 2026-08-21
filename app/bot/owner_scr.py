from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config.settings import LASTFM_SCR_MAX_PLAYS, is_code_owner
from app.services.lastfm_scrobbler import (
    ScrobbleItem,
    check_lastfm_auth,
    lastfm_auth_url,
    lastfm_get_auth_token,
    lastfm_get_session,
    save_persisted_session,
    scrobble_items,
)

logger = logging.getLogger(__name__)
router = Router(name="owner_scr")

_TAG_RE = re.compile(r"<[^>]+>")
_MUSIC_LINE_RE = re.compile(
    r"(?:♫|♪|♬)\s*(?:(\d+)\s*[·.]\s*)?(.+?)\s+[—–-]\s+(.+?)\s*$",
    re.MULTILINE,
)
_COUNT_RE = re.compile(r"^\d+$")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


@dataclass
class _PendingScr:
    artist: str
    track: str
    album: str | None
    count: int | None
    awaiting: str


_PENDING: dict[int, _PendingScr] = {}
_BUSY: set[int] = set()
_AUTH_TOKENS: dict[int, str] = {}


def _html_to_text(value: str) -> str:
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(value)
        extractor.close()
        text = extractor.text()
    except Exception:
        text = _TAG_RE.sub("", value)
    return html.unescape(text).replace("\xa0", " ").strip()


def parse_track_from_caption(raw: str | None) -> tuple[str, str, str | None] | None:
    """Extract (track, artist, album) from a bot music caption in DM."""
    text = _html_to_text(raw or "")
    if not text:
        return None
    for line in text.splitlines():
        compact = " ".join(line.split())
        match = _MUSIC_LINE_RE.search(compact)
        if not match:
            continue
        track = (match.group(2) or "").strip(" ·•|-")
        artist = (match.group(3) or "").strip(" ·•|-")
        if track and artist:
            return track[:200], artist[:200], None
    return None


def parse_play_count(raw: str | None, *, max_plays: int = LASTFM_SCR_MAX_PLAYS) -> int | None:
    token = str(raw or "").strip()
    if not _COUNT_RE.fullmatch(token):
        return None
    count = int(token)
    if count < 1 or count > max_plays:
        return None
    return count


def caption_from_message(message: Message | None) -> str:
    if message is None:
        return ""
    return (message.caption or message.text or "").strip()


def _is_owner_dm(message: Message) -> bool:
    return bool(
        message.from_user
        and message.chat
        and message.chat.type == "private"
        and is_code_owner(message.from_user.id)
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Concordo", callback_data="scr:y"),
                InlineKeyboardButton(text="Não", callback_data="scr:n"),
            ]
        ]
    )


def _track_from_reply(message: Message) -> tuple[str, str, str | None] | None:
    reply = message.reply_to_message
    if reply is None:
        return None
    return parse_track_from_caption(caption_from_message(reply))


async def _deny_if_needed(message: Message) -> bool:
    if not message.from_user:
        return True
    if not is_code_owner(message.from_user.id):
        return True
    if message.chat.type != "private":
        await message.answer("Use /scr e /sct só no privado, respondendo uma música.")
        return True
    return False


def _pending_for(user_id: int) -> _PendingScr | None:
    return _PENDING.get(int(user_id))


def _set_pending(user_id: int, pending: _PendingScr) -> None:
    _PENDING[int(user_id)] = pending


def _clear_pending(user_id: int) -> None:
    _PENDING.pop(int(user_id), None)


def _job_text(pending: _PendingScr, *, lastfm_user: str | None = None) -> str:
    track = html.escape(pending.track)
    artist = html.escape(pending.artist)
    count = pending.count or 0
    account = f"\nConta Last.fm: <b>{html.escape(lastfm_user)}</b>" if lastfm_user else ""
    return (
        f"Scrobblar <b>{track}</b> — <i>{artist}</i>\n"
        f"Plays: <code>{count}</code>{account}\n\n"
        "Confirma?"
    )


async def _ask_confirm(message: Message, pending: _PendingScr) -> None:
    auth = await check_lastfm_auth()
    if not auth.ok:
        await message.answer(
            "Last.fm não autenticou o scrobble.\n"
            f"{html.escape(auth.message or 'Confira TR3_LASTFM_SESSION_KEY e TR3_LASTFM_API_SECRET.')}",
            parse_mode="HTML",
        )
        return
    await message.answer(
        _job_text(pending, lastfm_user=auth.username),
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(),
    )


def _waiting_sct_count(message: Message) -> bool:
    user = message.from_user
    if not user:
        return False
    pending = _PENDING.get(int(user.id))
    return bool(pending and pending.awaiting == "count")


@router.message(Command("scr"))
async def scr_command(message: Message, command: CommandObject) -> None:
    if await _deny_if_needed(message):
        return
    assert message.from_user
    user_id = int(message.from_user.id)
    if user_id in _BUSY:
        await message.answer("Já tem um scrobble em andamento. Espera terminar.")
        return
    parsed = _track_from_reply(message)
    if parsed is None:
        await message.answer("Responda uma música que o bot mandou na DM com <code>/scr 123</code>.", parse_mode="HTML")
        return
    count = parse_play_count(command.args if command else None)
    if count is None:
        await message.answer(
            f"Uso: responda a música com <code>/scr 123</code>. Número de 1 a {LASTFM_SCR_MAX_PLAYS}.",
            parse_mode="HTML",
        )
        return
    track, artist, album = parsed
    pending = _PendingScr(artist=artist, track=track, album=album, count=count, awaiting="confirm")
    _set_pending(user_id, pending)
    await _ask_confirm(message, pending)


@router.message(Command("sct"))
async def sct_command(message: Message) -> None:
    if await _deny_if_needed(message):
        return
    assert message.from_user
    user_id = int(message.from_user.id)
    if user_id in _BUSY:
        await message.answer("Já tem um scrobble em andamento. Espera terminar.")
        return
    parsed = _track_from_reply(message)
    if parsed is None:
        await message.answer("Responda uma música que o bot mandou na DM com <code>/sct</code>.", parse_mode="HTML")
        return
    track, artist, album = parsed
    _set_pending(
        user_id,
        _PendingScr(artist=artist, track=track, album=album, count=None, awaiting="count"),
    )
    await message.answer(
        f"Quantos plays no Last.fm para <b>{html.escape(track)}</b> — <i>{html.escape(artist)}</i>?\n"
        f"Manda um número de 1 a {LASTFM_SCR_MAX_PLAYS}.",
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True, input_field_placeholder="ex: 123"),
    )


@router.message(
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    _waiting_sct_count,
)
async def sct_count_reply(message: Message) -> None:
    if not message.from_user or not is_code_owner(message.from_user.id):
        return
    user_id = int(message.from_user.id)
    pending = _pending_for(user_id)
    if pending is None or pending.awaiting != "count":
        return
    count = parse_play_count(message.text)
    if count is None:
        await message.answer(
            f"Número inválido. Manda um inteiro de 1 a {LASTFM_SCR_MAX_PLAYS}.",
        )
        return
    pending.count = count
    pending.awaiting = "confirm"
    _set_pending(user_id, pending)
    await _ask_confirm(message, pending)


@router.callback_query(F.data.in_({"scr:y", "scr:n"}))
async def scr_confirm_callback(query: CallbackQuery) -> None:
    if not query.from_user or not is_code_owner(query.from_user.id):
        await query.answer("Acesso indisponível.", show_alert=True)
        return
    if query.message is None or getattr(query.message.chat, "type", None) != "private":
        await query.answer("Só no privado.", show_alert=True)
        return
    user_id = int(query.from_user.id)
    pending = _pending_for(user_id)
    if pending is None or pending.awaiting != "confirm" or pending.count is None:
        await query.answer("Pedido expirado. Manda /scr de novo.", show_alert=True)
        return
    if query.data == "scr:n":
        _clear_pending(user_id)
        await query.answer("Cancelado.")
        try:
            await query.message.edit_text("Scrobble cancelado.")
        except Exception:
            pass
        return
    if user_id in _BUSY:
        await query.answer("Já está enviando.", show_alert=True)
        return

    _BUSY.add(user_id)
    count = pending.count
    items = [
        ScrobbleItem(artist=pending.artist, track=pending.track, album=pending.album)
        for _ in range(count)
    ]
    _clear_pending(user_id)
    await query.answer("Enviando…")
    try:
        await query.message.edit_text(
            f"Enviando <code>{count}</code> plays de <b>{html.escape(pending.track)}</b>…",
            parse_mode="HTML",
        )
    except Exception:
        pass
    try:
        result = await scrobble_items(items)
    except Exception:
        logger.exception("OWNER_SCR_FAILED user=%s track=%s count=%s", user_id, pending.track, count)
        _BUSY.discard(user_id)
        await query.message.answer("Falhou ao falar com o Last.fm. Tenta de novo.")
        return
    _BUSY.discard(user_id)

    extra = ""
    if result.daily_limit_hit:
        extra = "\nLast.fm bateu o limite diário."
    elif result.rate_limit_hit:
        extra = "\nLast.fm pediu para ir mais devagar."
    elif result.stopped_early:
        extra = "\nParou no meio; o restante não foi enviado."
    if result.api_errors:
        extra += f"\n{html.escape(result.api_errors[0][:180])}"
    await query.message.answer(
        f"<b>{html.escape(pending.track)}</b> — <i>{html.escape(pending.artist)}</i>\n"
        f"Pedidos: <code>{result.requested}</code>\n"
        f"Aceitos: <code>{result.accepted}</code>\n"
        f"Ignorados: <code>{result.ignored}</code>{extra}",
        parse_mode="HTML",
    )


def _auth_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Autorizar no Last.fm", url=url)],
            [InlineKeyboardButton(text="Já autorizei", callback_data="lfmauth:done")],
        ]
    )


async def _start_lfmauth(message: Message, user_id: int) -> None:
    token, error = await lastfm_get_auth_token()
    if not token:
        await message.answer(
            "Não consegui abrir a autorização.\n"
            f"{html.escape(error or 'Confira TR3_LASTFM_API_KEY e TR3_LASTFM_API_SECRET no Railway.')}",
            parse_mode="HTML",
        )
        return
    _AUTH_TOKENS[user_id] = token
    url = lastfm_auth_url(token)
    await message.answer(
        "1. Toque em <b>Autorizar no Last.fm</b>\n"
        "2. Confirme com a conta que deve receber os scrobbles\n"
        "3. Volte aqui e toque em <b>Já autorizei</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_auth_keyboard(url),
    )


@router.message(Command("lfmauth"))
async def lfmauth_command(message: Message) -> None:
    if await _deny_if_needed(message):
        return
    assert message.from_user
    user_id = int(message.from_user.id)
    auth = await check_lastfm_auth()
    if auth.ok:
        await message.answer(
            f"Last.fm já autorizado como <b>{html.escape(auth.username or '?')}</b>.\n"
            "Manda /lfmauth de novo se quiser trocar de conta.",
            parse_mode="HTML",
        )
        # Still allow a fresh link if they explicitly want to reconnect:
        # only skip extra prompt; they can send /lfmauth twice. Start anyway if they
        # used the command — they asked to authorize.
    await _start_lfmauth(message, user_id)


@router.callback_query(F.data == "lfmauth:done")
async def lfmauth_done(query: CallbackQuery) -> None:
    if not query.from_user or not is_code_owner(query.from_user.id):
        await query.answer("Acesso indisponível.", show_alert=True)
        return
    if query.message is None or getattr(query.message.chat, "type", None) != "private":
        await query.answer("Só no privado.", show_alert=True)
        return
    user_id = int(query.from_user.id)
    token = _AUTH_TOKENS.get(user_id)
    if not token:
        await query.answer("Pedido expirado. Manda /lfmauth de novo.", show_alert=True)
        return
    await query.answer("Conferindo…")
    sk, username, error = await lastfm_get_session(token)
    if not sk:
        await query.message.answer(
            html.escape(error or "Ainda não autorizou. Abre o link, confirma, e toca de novo em Já autorizei."),
        )
        return
    saved = save_persisted_session(sk=sk, username=username or "")
    _AUTH_TOKENS.pop(user_id, None)
    check = await check_lastfm_auth()
    if check.ok:
        await query.message.answer(
            f"Pronto. Last.fm conectado como <b>{html.escape(check.username or username or '?')}</b>.\n"
            "Pode testar: responde um card com <code>/scr 1</code>.",
            parse_mode="HTML",
        )
        return
    if saved:
        await query.message.answer(
            "Salvei a sessão, mas o Last.fm ainda não confirmou. Espera um instante e tenta /scr 1.",
        )
        return
    await query.message.answer(
        "Autorizei, mas não consegui gravar no disco do servidor.\n"
        "Cola isso no Railway como <code>TR3_LASTFM_SESSION_KEY</code> e faz redeploy:\n"
        f"<code>{html.escape(sk)}</code>",
        parse_mode="HTML",
    )

