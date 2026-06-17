"""Router real mínimo do painel Tigrão FSM."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config.settings import CODE_OWNER_IDS, TIGRAO_FSM_MODERATOR_IDS
from app.bot.music_groups import list_groups

from ..keyboards import (
    back_close_keyboard,
    group_admin_keyboard,
    group_selection_keyboard,
    home_keyboard,
    logs_keyboard,
    parse_callback,
    to_inline_keyboard_markup,
)
from ..permissions import is_authorized_user, permissions_from_chat_member
from ..state import close_session, create_session, get_session

logger = logging.getLogger(__name__)
router = Router(name="tigrao_fsm_panel")

HOME_TEXT = "Tigrão"
SESSION_EXPIRED_TEXT = "Sessão expirada. Use /tigrao novamente."


def _uid(obj: Any) -> int | None:
    user = getattr(obj, "from_user", None)
    try:
        return int(getattr(user, "id"))
    except Exception:
        return None


def _authorized(user_id: int | None) -> bool:
    return is_authorized_user(user_id, owner_ids=CODE_OWNER_IDS, moderator_ids=TIGRAO_FSM_MODERATOR_IDS)


def _home_markup(session_id: str) -> Any:
    return to_inline_keyboard_markup(home_keyboard(session_id))


async def _safe_edit(callback: CallbackQuery, text: str, markup: Any) -> None:
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        await message.edit_text(text, reply_markup=markup)
    else:
        await callback.answer()


@router.message(Command("tigrao"))
async def tigrao_panel(message: Message, bot: Any) -> None:
    user_id = _uid(message)
    if not _authorized(user_id):
        return
    session = create_session(owner_user_id=user_id, moderator_user_id=user_id)
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) == "private":
        await message.answer(HOME_TEXT, reply_markup=_home_markup(session.session_id))
        return
    try:
        await bot.send_message(user_id, HOME_TEXT, reply_markup=_home_markup(session.session_id))
    except Exception:
        logger.debug("TIGRAO_PANEL_DM_FAILED", exc_info=True)


@router.callback_query(F.data.startswith("tgf:"))
async def tigrao_callback(callback: CallbackQuery, bot: Any) -> None:
    user_id = _uid(callback)
    if not _authorized(user_id):
        await callback.answer()
        return
    parsed = parse_callback(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    session_id, parts = parsed
    action = parts[0]
    session = get_session(session_id)
    if session is None:
        await _safe_edit(callback, SESSION_EXPIRED_TEXT, None)
        await callback.answer()
        return
    owner = session.moderator_user_id or session.owner_user_id
    if owner is not None and owner != user_id:
        await callback.answer()
        return

    if action == "close":
        close_session(session_id)
        try:
            if callback.message is not None:
                await callback.message.delete()
            await callback.answer()
            return
        except Exception:
            if callback.message is not None:
                await callback.message.edit_text("Painel fechado.")
            await callback.answer()
            return

    if action in {"home", "back"}:
        await _safe_edit(callback, HOME_TEXT, _home_markup(session_id))
    elif action == "grp":
        await _show_groups(callback, session_id)
    elif action.startswith("g") and action[1:].isdecimal():
        await _show_group_detail(callback, bot, session_id, int(action[1:]))
    elif action == "logs":
        await _safe_edit(callback, "Logs do Tigrão", to_inline_keyboard_markup(logs_keyboard(session_id)))
    elif action == "join":
        await _safe_edit(callback, "Solicitações de entrada\n\nPonte preparada. Aprovação automática não está ativa nesta etapa.", to_inline_keyboard_markup(back_close_keyboard(session_id)))
    else:
        await callback.answer()
        return
    await callback.answer()


async def _show_groups(callback: CallbackQuery, session_id: str) -> None:
    session = get_session(session_id)
    if session is None:
        await _safe_edit(callback, SESSION_EXPIRED_TEXT, None)
        return
    try:
        groups = list_groups(limit=50)
    except Exception:
        logger.debug("TIGRAO_GROUP_LIST_FAILED", exc_info=True)
        groups = []
    session.payload["groups"] = [{"chat_id": int(g["chat_id"]), "title": g.get("title") or g.get("username") or str(g["chat_id"])} for g in groups[:50] if g.get("chat_id") is not None]
    if not session.payload["groups"]:
        await _safe_edit(callback, "Nenhum grupo disponível para seleção agora.", to_inline_keyboard_markup(back_close_keyboard(session_id)))
        return
    await _safe_edit(callback, "Selecione um grupo:", to_inline_keyboard_markup(group_selection_keyboard(session_id, session.payload["groups"])))


async def _show_group_detail(callback: CallbackQuery, bot: Any, session_id: str, index: int) -> None:
    session = get_session(session_id)
    groups = (session.payload.get("groups") if session else None) or []
    if index < 0 or index >= len(groups):
        await callback.answer()
        return
    group = groups[index]
    chat_id = int(group["chat_id"])
    title = str(group.get("title") or chat_id)
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        perms = permissions_from_chat_member(member)
    except Exception:
        logger.debug("TIGRAO_GROUP_PERMISSIONS_FAILED", exc_info=True)
        perms = None
    if perms is None or not perms.is_admin:
        text = (f"Grupo selecionado: {title}\nID do grupo: {chat_id}\nStatus do bot: não administrador\n"
                "Painel indisponível para este grupo.\nPromova o bot a administrador para usar o Tigrão aqui.")
        await _safe_edit(callback, text, to_inline_keyboard_markup(back_close_keyboard(session_id)))
        return
    yesno = lambda v: "sim" if v else "não"
    text = (f"Grupo selecionado: {title}\nID do grupo: {chat_id}\nStatus do bot: administrador\n\n"
            f"Apagar mensagens: {yesno(perms.can_delete_messages)}\n"
            f"Restringir membros: {yesno(perms.can_restrict_members)}\n"
            f"Convidar/aprovar entradas: {yesno(perms.can_invite_users)}\n"
            f"Fixar mensagens: {yesno(perms.can_pin_messages)}\n"
            f"Alterar informações: {yesno(perms.can_change_info)}\n"
            f"Tags: {yesno(perms.can_manage_tags)}\n"
            f"Tópicos: {yesno(perms.can_manage_topics)}")
    await _safe_edit(callback, text, to_inline_keyboard_markup(group_admin_keyboard(session_id)))
