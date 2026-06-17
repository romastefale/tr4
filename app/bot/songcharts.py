from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.services.lastfm import lastfm_service
from app.services.lastfm_group import lastfm_group_service
from app.services.monthfm_card import render_monthfm_card

logger = logging.getLogger(__name__)
router = Router(name="songcharts")

# I4: mantém ref forte das background tasks pra GC não coletar antes do término.
# Pattern recomendado pelo Python docs (asyncio.create_task).
_BG_TASKS: set[asyncio.Task] = set()


def _spawn_bg(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task

# Concorrência ao checar presença no grupo (get_chat_member). Cada
# checagem é uma chamada Bot API — paraleliza pra não bloquear, mas sem
# explodir o flood limit. Em prática: 30 conectados resolve em <1s.
MEMBER_CHECK_CONCURRENCY = 8
NON_MEMBER_STATUSES = {"left", "ki" + "cked"}


def _menu_keyboard(scope: str, chat_id: int, requester_id: int) -> InlineKeyboardMarkup:
    """Botões pra escolher o período do ranking.

    `scope` ∈ {"g","a"}: g=membros do grupo, a=todos conectados.
    `chat_id` é usado no fluxo de grupo pra repetir o filtro no callback.
    """
    # Bot API 9.4 (fev/2026): style="success" (verde) / "danger" (vermelho)
    # nos InlineKeyboardButton. aiogram 3.27 expõe nativo. Sem emoji.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Semanal",
                    callback_data=f"songcharts:{scope}:w:{chat_id}:{requester_id}",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="Mensal",
                    callback_data=f"songcharts:{scope}:m:{chat_id}:{requester_id}",
                    style="danger",
                ),
            ]
        ]
    )


async def _members_in_chat(
    bot: Bot, chat_id: int, profiles: list[tuple[int, str]]
) -> list[tuple[int, str]]:
    """Filtra `profiles` retendo só quem está no grupo `chat_id`.

    Roda `get_chat_member` com `Semaphore(8)`; falhas individuais são
    silenciadas (usuário fica fora do ranking).
    """
    if not profiles:
        return []
    semaphore = asyncio.Semaphore(MEMBER_CHECK_CONCURRENCY)

    async def _check(user_id: int, username: str) -> tuple[int, str] | None:
        async with semaphore:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
            except Exception:
                return None
            status = getattr(member, "status", None)
            if status and status not in NON_MEMBER_STATUSES:
                return (user_id, username)
            return None

    results = await asyncio.gather(*(_check(uid, uname) for uid, uname in profiles))
    return [r for r in results if r is not None]


def _dm_deny_text() -> str:
    return (
        "♫ <b>/songcharts</b> só funciona em grupo. "
        "Rode o comando no grupo onde a galera escuta junto."
    )


@router.message(Command("songcharts"))
async def songcharts(message: Message) -> None:
    if not message.from_user or not message.bot:
        return
    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "songcharts"):
        return
    requester = message.from_user
    chat = message.chat

    if chat.type == "private":
        await message.answer(_dm_deny_text(), parse_mode="HTML")
        return

    await message.answer(
        f"♫ Ranking de <b>{html.escape(chat.title or 'grupo')}</b>.\n"
        "Escolha o período:",
        parse_mode="HTML",
        reply_markup=_menu_keyboard(scope="g", chat_id=chat.id, requester_id=requester.id),
    )


async def _safe_edit(message: Message, text: str) -> Message:
    try:
        await message.edit_text(text, parse_mode="HTML")
        return message
    except Exception:
        logger.warning("SONGCHARTS_EDIT_FAILED", exc_info=True)
        return await message.answer(text, parse_mode="HTML")


async def _render_and_send(
    *,
    bot: Bot,
    target_chat_id: int,
    chat_title: str,
    members: list[tuple[int, str]],
    period_kind: str,
    status_message: Message,
) -> None:
    try:
        result = await lastfm_group_service.build_group_capsule(
            chat_title=chat_title,
            members=members,
            period_kind=period_kind,  # type: ignore[arg-type]
        )
    except Exception:
        logger.exception("SONGCHARTS_BUILD_FAILED | chat_id=%s", target_chat_id)
        try:
            await status_message.edit_text("Não consegui montar o ranking agora. Tente em alguns instantes.")
        except Exception:
            logger.warning("SONGCHARTS_FAILURE_EDIT_FAILED", exc_info=True)
        return

    card_bytes = await render_monthfm_card(result.card_data) if result.card_data else None
    period_value = ""
    if result.card_data is not None and result.card_data.period_value:
        period_value = result.card_data.period_value.lower()
    safe_title = html.escape(chat_title)
    # Caption literal pedida pelo user: "Top 10 de <grupo> · <período>".
    # Sem prefixo de glifo — quanto mais enxuto, melhor pra mensagem fixa.
    caption = f"Top 10 de {safe_title}" + (
        f" · {html.escape(period_value)}" if period_value else ""
    )

    sent: Message | None = None
    if card_bytes:
        sent = await bot.send_photo(
            chat_id=target_chat_id,
            photo=BufferedInputFile(card_bytes, filename="songcharts.jpg"),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        # Sem card: cai pro texto descritivo (top 10 detalhado).
        sent = await bot.send_message(
            chat_id=target_chat_id,
            text=result.text,
            parse_mode="HTML",
        )
    # Bot reage 🏆 no card de ranking musical.
    if sent is not None:
        from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_EXTRACT
        await _react_to_own_card(bot, sent.chat.id, sent.message_id, _CARD_EMOJI_EXTRACT)


async def _run_group_flow(
    *,
    bot: Bot,
    chat_id: int,
    chat_title: str,
    period_kind: str,
    status_message: Message,
) -> None:
    profiles = await lastfm_service.get_all_profiles()
    members = await _members_in_chat(bot, chat_id, profiles)
    await _render_and_send(
        bot=bot,
        target_chat_id=chat_id,
        chat_title=chat_title,
        members=members,
        period_kind=period_kind,
        status_message=status_message,
    )


async def _run_global_flow(
    *,
    bot: Bot,
    target_chat_id: int,
    period_kind: str,
    status_message: Message,
) -> None:
    profiles = await lastfm_service.get_all_profiles()
    await _render_and_send(
        bot=bot,
        target_chat_id=target_chat_id,
        chat_title="Todos conectados",
        members=profiles,
        period_kind=period_kind,
        status_message=status_message,
    )


@router.callback_query(F.data.startswith("songcharts:"))
async def songcharts_callback(query: CallbackQuery) -> None:
    if not query.from_user or not query.data or not query.message or not query.bot:
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer()
        return
    _, scope, period, raw_chat, raw_requester = parts
    try:
        chat_id = int(raw_chat)
        requester_id = int(raw_requester)
    except ValueError:
        await query.answer()
        return
    if scope not in {"g", "a"} or period not in {"w", "m"}:
        await query.answer()
        return

    if scope == "g":
        # Defesa contra hijack/replay: o callback só vale quando rodado no
        # MESMO chat onde o menu foi criado (callback_data não pode ser
        # reutilizado em outro grupo).
        if query.message.chat.id != chat_id:
            await query.answer("Menu inválido para este chat.", show_alert=True)
            return
    else:  # scope == "a" desativado no build music-only
        await query.answer("Ranking global por DM não está disponível neste build.", show_alert=True)
        return

    if query.from_user.id != requester_id:
        # Botão foi gerado por outro user — bloqueia pra evitar disputa.
        await query.answer(
            "Esse menu é da outra pessoa. Rode /songcharts você também.",
            show_alert=True,
        )
        return

    await query.answer()
    label_periodo = "semana" if period == "w" else "mês"

    # U1: chat_action enquanto Playwright renderiza o card (5-15s).
    try:
        await query.bot.send_chat_action(query.message.chat.id, "upload_photo")
    except Exception:
        pass

    if scope == "g":
        chat_title = query.message.chat.title or "grupo"
        status = await _safe_edit(
            query.message,
            f"Gerando ranking do {label_periodo} de <b>{html.escape(chat_title)}</b>...",
        )
        _spawn_bg(
            _run_group_flow(
                bot=query.bot,
                chat_id=chat_id,
                chat_title=chat_title,
                period_kind="week" if period == "w" else "month",
                status_message=status,
            )
        )
    else:
        status = await _safe_edit(
            query.message,
            f"Gerando ranking global do {label_periodo} (todos conectados)...",
        )
        _spawn_bg(
            _run_global_flow(
                bot=query.bot,
                target_chat_id=query.message.chat.id,
                period_kind="week" if period == "w" else "month",
                status_message=status,
            )
        )
