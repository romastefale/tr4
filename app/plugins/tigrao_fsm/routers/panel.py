"""Router real mínimo do painel Tigrão FSM."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message

from app.config.settings import (
    CODE_OWNER_IDS,
    TIGRAO_FSM_DDX_HARD_ENABLED,
    TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED,
    TIGRAO_FSM_MODERATOR_IDS,
    TIGRAO_FSM_REACTIONS_ENABLED,
)
from app.bot.music_groups import list_groups

from .. import storage
from ..keyboards import (
    back_close_keyboard,
    confirm_cancel_keyboard,
    ddx_keyboard,
    destructive_actions_keyboard,
    group_admin_keyboard,
    group_selection_keyboard,
    home_keyboard,
    join_auto_question_keyboard,
    join_requests_keyboard,
    logs_keyboard,
    parse_callback,
    to_inline_keyboard_markup,
)
from ..parsers import parse_user_ids
from ..destructive_actions import DestructiveActionRequest, execute_destructive_action
from ..permissions import get_bot_permissions, is_authorized_user, permissions_from_chat_member
from ..services import approve_pending_join_request, create_join_request_link, format_logs
from ..state import close_session, create_session, get_session, get_user_session

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


class TigraoWaitingTextFilter(Filter):
    """Permite capturar texto privado somente quando o painel espera resposta.

    Sem este filtro, um handler genérico de texto do Tigrão poderia interceptar
    mensagens privadas comuns do owner/moderador e impedir outros fluxos do bot.
    """

    async def __call__(self, message: Message) -> bool:
        user_id = _uid(message)
        if not _authorized(user_id):
            return False
        chat = getattr(message, "chat", None)
        if getattr(chat, "type", None) != "private":
            return False
        session = get_user_session(user_id)
        return bool(session is not None and session.waiting_for)


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


@router.message(TigraoWaitingTextFilter(), F.text)
async def tigrao_waiting_message(message: Message, bot: Any) -> None:
    """Processa respostas de DM quando a sessão do painel está aguardando texto."""
    user_id = _uid(message)
    if not _authorized(user_id):
        return
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) != "private":
        return
    session = get_user_session(user_id)
    if session is None or not session.waiting_for:
        return
    text = str(getattr(message, "text", "") or "").strip()
    if session.waiting_for == "join_auto_ids":
        await _handle_join_auto_ids(message, bot, session, text)
    elif session.waiting_for == "join_pending_id":
        await _handle_join_pending_id(message, bot, session, text)
    elif session.waiting_for == "destructive_user_id":
        await _handle_destructive_user_id(message, session, text)
    elif session.waiting_for == "destructive_message_id":
        await _handle_destructive_message_id(message, session, text)
    elif session.waiting_for == "ddx_filter_text":
        await _handle_ddx_filter_text(message, session, text)
    elif session.waiting_for == "ddx_remove_id":
        await _handle_ddx_remove_id(message, session, text)


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
        session.waiting_for = None
        await _safe_edit(callback, HOME_TEXT, _home_markup(session_id))
    elif action == "grp":
        session.waiting_for = None
        await _show_groups(callback, session_id)
    elif action.startswith("g") and action[1:].isdecimal():
        session.waiting_for = None
        await _show_group_detail(callback, bot, session_id, int(action[1:]))
    elif action == "logs":
        await _safe_edit(callback, "Logs do Tigrão", to_inline_keyboard_markup(logs_keyboard(session_id)))
    elif action in {"log_mod", "log_music", "log_use", "log_join", "log_err"}:
        await _show_logs(callback, session, action)
    elif action == "join":
        await _show_join_menu(callback, session_id)
    elif action == "join_link":
        await _create_join_link(callback, bot, session)
    elif action == "join_noauto":
        await _show_join_menu(callback, session_id, "Link criado sem autoaceite adicional.")
    elif action == "join_auto":
        await _join_auto_or_list(callback, session)
    elif action == "join_pending":
        await _join_pending(callback, session)
    elif action == "act":
        await _show_actions(callback, session)
    elif action in {"ban", "unban", "mute1h", "mute24h", "muteforever", "unmute"}:
        await _prompt_destructive_user(callback, session, action)
    elif action == "delmsg":
        await _prompt_delete_message(callback, session)
    elif action == "confirm":
        await _confirm_pending_action(callback, bot, session)
    elif action == "cancel":
        session.selected_action = None
        session.payload.pop("pending_destructive_action", None)
        await _safe_edit(callback, "Ação cancelada.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
    elif action == "ddx":
        await _show_ddx(callback, session)
    elif action == "ddxon":
        await _set_ddx_enabled(callback, session, True)
    elif action == "ddxoff":
        await _set_ddx_enabled(callback, session, False)
    elif action == "ddxadd":
        await _prompt_ddx_filter(callback, session)
    elif action == "ddxlist":
        await _list_ddx(callback, session)
    elif action == "ddxremove":
        await _prompt_ddx_remove(callback, session)
    elif action == "react":
        await _safe_edit(callback, "Reações ainda não implementadas nesta fase. Recurso mantido indisponível com segurança.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
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
    session.selected_chat_id = chat_id
    session.selected_group_title = title
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
    await _safe_edit(callback, text, to_inline_keyboard_markup(group_admin_keyboard(
        session_id,
        destructive_actions_enabled=TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED,
        ddx_enabled=TIGRAO_FSM_DDX_HARD_ENABLED,
        reactions_enabled=TIGRAO_FSM_REACTIONS_ENABLED,
    )))


def _selected_group_or_text(session: Any) -> tuple[int | None, str | None, str | None]:
    if session.selected_chat_id is None:
        return None, None, "Selecione um grupo antes de usar esta função."
    return int(session.selected_chat_id), session.selected_group_title or str(session.selected_chat_id), None


async def _show_join_menu(callback: CallbackQuery, session_id: str, prefix: str | None = None) -> None:
    text = "Solicitações de entrada"
    if prefix:
        text = f"{prefix}\n\n{text}"
    await _safe_edit(callback, text, to_inline_keyboard_markup(join_requests_keyboard(session_id)))


async def _create_join_link(callback: CallbackQuery, bot: Any, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    try:
        perms = await get_bot_permissions(bot, chat_id)
        if not perms.is_admin or not perms.can_invite_users:
            raise PermissionError("bot sem can_invite_users")
        invite = await create_join_request_link(bot, chat_id, name="Tigrão FSM")
    except Exception as exc:
        storage.log_event(
            action="join_link_create",
            result="falhou",
            detection="direta",
            surface="callback",
            chat_id=chat_id,
            chat_title=title,
            actor_user_id=session.moderator_user_id or session.owner_user_id,
            details=str(exc),
        )
        await _safe_edit(callback, f"Falha ao criar link com solicitação: {exc}", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    link = getattr(invite, "invite_link", None) or getattr(invite, "link", None) or str(invite)
    session.payload["last_invite_link"] = link
    storage.log_event(
        action="join_link_create",
        result="criado",
        detection="direta",
        surface="callback",
        chat_id=chat_id,
        chat_title=title,
        actor_user_id=session.moderator_user_id or session.owner_user_id,
        details="Link com solicitação criado.",
        metadata={"invite_link": link},
    )
    text = f"Link criado com solicitação.\n\n{link}\n\nDeseja ativar autoaceite para IDs específicos?"
    await _safe_edit(callback, text, to_inline_keyboard_markup(join_auto_question_keyboard(session.session_id)))


async def _join_auto_or_list(callback: CallbackQuery, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    if session.payload.get("last_invite_link"):
        session.waiting_for = "join_auto_ids"
        await _safe_edit(callback, "Envie um ou mais IDs Telegram. Pode separar por espaço, vírgula ou quebra de linha.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    rows = storage.list_auto_accepts(chat_id=chat_id, limit=10)
    if not rows:
        text = "Nenhuma autorização automática ativa encontrada."
    else:
        text = "Autorizações automáticas\n\n" + "\n".join(
            f"ID: {row.allowed_user_id} — status: {row.status} — expira: {row.expires_at.isoformat()}" for row in rows
        )
    await _safe_edit(callback, text, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _join_pending(callback: CallbackQuery, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    pending = storage.list_pending_join_requests(chat_id=chat_id, limit=10)
    lines = ["Pendentes 2h"]
    if not pending:
        lines.append("Nenhuma solicitação pendente encontrada.")
    else:
        for req in pending:
            username = f"@{req.username}" if req.username else "não informado"
            lines.append(f"Usuário: {req.full_name}\nUsername: {username}\nID: {req.user_id}")
    lines.append("\nPara aceitar um ID pendente, envie o ID numérico nesta DM.")
    session.waiting_for = "join_pending_id"
    await _safe_edit(callback, "\n\n".join(lines), to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _handle_join_auto_ids(message: Message, bot: Any, session: Any, text: str) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    parsed = parse_user_ids(text)
    link = str(session.payload.get("last_invite_link") or "")
    if not link:
        await message.answer("Nenhum link com solicitação foi criado nesta sessão.")
        session.waiting_for = None
        return
    records = storage.create_auto_accept_records(
        chat_id=chat_id,
        chat_title=title,
        invite_link=link,
        user_ids=parsed.valid,
        created_by_owner_id=session.moderator_user_id or session.owner_user_id or 0,
    )
    approved_now = 0
    for user_id in parsed.valid:
        req = storage.find_pending_join_request(chat_id=chat_id, user_id=user_id)
        if req is None:
            continue
        try:
            perms = await get_bot_permissions(bot, chat_id)
            if not perms.is_admin or not perms.can_invite_users:
                continue
            detail = await approve_pending_join_request(bot, req, processed_by=session.moderator_user_id or session.owner_user_id, autoaccept=True, origin="ID autorizado no painel")
            storage.update_join_request_status(req)
            auto = storage.get_active_auto_accept(chat_id=chat_id, user_id=user_id)
            if auto is not None:
                auto.status = storage.APPROVED if req.status == "aprovado" else storage.FAILED
                auto.approved_at = req.processed_at
                auto.result_detail = detail
                storage.update_auto_accept_status(auto)
            if req.status == "aprovado":
                approved_now += 1
            storage.log_event(action="join_auto_accept", result=req.status, detection="indireta", surface="banco_pendente", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, target_user_id=user_id, details=detail)
        except Exception as exc:
            storage.log_event(action="join_auto_accept", result="falhou", detection="indireta", surface="banco_pendente", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, target_user_id=user_id, details=str(exc))
    waiting_future = max(0, len(parsed.valid) - approved_now)
    storage.log_event(action="join_auto_ids_saved", result="salvo", detection="direta", surface="dm", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, details=f"IDs autorizados: {len(records)}; inválidos: {len(parsed.invalid)}")
    session.waiting_for = None
    session.payload.pop("last_invite_link", None)
    invalid_text = "\n".join(parsed.invalid) if parsed.invalid else "nenhum"
    await message.answer(
        f"Autoaceite ativado por 2h.\n"
        f"IDs autorizados: {len(parsed.valid)}\n"
        f"Pendentes aprovados agora: {approved_now}\n"
        f"Aguardando solicitação futura: {waiting_future}\n"
        f"Inválidos ignorados: {len(parsed.invalid)}\n{invalid_text}"
    )


async def _handle_join_pending_id(message: Message, bot: Any, session: Any, text: str) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    parsed = parse_user_ids(text)
    if len(parsed.valid) != 1:
        await message.answer("Envie exatamente um ID Telegram numérico válido.")
        return
    user_id = parsed.valid[0]
    req = storage.find_pending_join_request(chat_id=chat_id, user_id=user_id)
    if req is None:
        await message.answer("Nenhuma solicitação pendente desse ID foi encontrada nas últimas 2h.")
        session.waiting_for = None
        return
    try:
        perms = await get_bot_permissions(bot, chat_id)
        if not perms.is_admin or not perms.can_invite_users:
            raise PermissionError("bot sem can_invite_users")
        detail = await approve_pending_join_request(bot, req, processed_by=session.moderator_user_id or session.owner_user_id, autoaccept=False, origin="aprovação manual por ID pendente")
        storage.update_join_request_status(req)
        storage.log_event(action="join_pending_approve", result=req.status, detection="indireta", surface="banco_pendente", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, target_user_id=user_id, details=detail)
        await message.answer(detail)
    except Exception as exc:
        storage.log_event(action="join_pending_approve", result="falhou", detection="indireta", surface="banco_pendente", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, target_user_id=user_id, details=str(exc))
        await message.answer(f"Falha ao aprovar ID pendente: {exc}")
    finally:
        session.waiting_for = None




async def _show_actions(callback: CallbackQuery, session: Any) -> None:
    if not TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED:
        await _safe_edit(callback, "Ações destrutivas indisponíveis. Ative TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    text = f"Ações do grupo\n\nGrupo: {title}\nID do grupo: {chat_id}\n\nToda ação exige confirmação explícita."
    await _safe_edit(callback, text, to_inline_keyboard_markup(destructive_actions_keyboard(session.session_id)))


_ACTION_LABELS = {
    "ban": "Banir usuário",
    "unban": "Desbanir usuário",
    "mute1h": "Mutar usuário por 1 hora",
    "mute24h": "Mutar usuário por 24 horas",
    "muteforever": "Mutar usuário indefinidamente",
    "unmute": "Desmutar usuário",
    "delmsg": "Apagar mensagem",
}


async def _prompt_destructive_user(callback: CallbackQuery, session: Any, action: str) -> None:
    if not TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED:
        await _safe_edit(callback, "Ações destrutivas indisponíveis.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    session.selected_action = action
    session.waiting_for = "destructive_user_id"
    await _safe_edit(callback, f"{_ACTION_LABELS[action]}\n\nEnvie o ID Telegram numérico do alvo.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _prompt_delete_message(callback: CallbackQuery, session: Any) -> None:
    if not TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED:
        await _safe_edit(callback, "Ações destrutivas indisponíveis.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    session.selected_action = "delmsg"
    session.waiting_for = "destructive_message_id"
    await _safe_edit(callback, "Apagar mensagem\n\nEnvie o message_id numérico da mensagem.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


def _positive_int(text: str) -> int | None:
    try:
        value = int(str(text).strip())
    except Exception:
        return None
    return value if value > 0 else None


async def _handle_destructive_user_id(message: Message, session: Any, text: str) -> None:
    user_id = _positive_int(text)
    if user_id is None:
        await message.answer("Envie um ID Telegram numérico positivo.")
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    action = str(session.selected_action or "")
    session.payload["pending_destructive_action"] = {"action": action, "target_user_id": user_id}
    session.waiting_for = None
    await message.answer(
        "Confirmar ação\n\n"
        f"Grupo: {title}\nID do grupo: {chat_id}\n\n"
        f"Ação: {_ACTION_LABELS.get(action, action)}\nID do alvo: {user_id}\n\n"
        "A ação real só será executada após confirmação.",
        reply_markup=to_inline_keyboard_markup(confirm_cancel_keyboard(session.session_id)),
    )


async def _handle_destructive_message_id(message: Message, session: Any, text: str) -> None:
    message_id = _positive_int(text)
    if message_id is None:
        await message.answer("Envie um message_id numérico positivo.")
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    session.payload["pending_destructive_action"] = {"action": "delmsg", "message_id": message_id}
    session.waiting_for = None
    await message.answer(
        "Confirmar ação\n\n"
        f"Grupo: {title}\nID do grupo: {chat_id}\n\n"
        f"Ação: Apagar mensagem\nID da mensagem: {message_id}\n\n"
        "A ação real só será executada após confirmação.",
        reply_markup=to_inline_keyboard_markup(confirm_cancel_keyboard(session.session_id)),
    )


async def _target_admin_status(bot: Any, chat_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return True
    try:
        member = await bot.get_chat_member(chat_id, int(user_id))
    except Exception:
        return False
    status = getattr(member, "status", None)
    status_value = getattr(status, "value", status)
    return status_value in {"administrator", "creator"}


async def _confirm_pending_action(callback: CallbackQuery, bot: Any, session: Any) -> None:
    if not TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED:
        session.payload.pop("pending_destructive_action", None)
        session.selected_action = None
        await _safe_edit(callback, "Ações destrutivas indisponíveis.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    pending = session.payload.get("pending_destructive_action")
    if not pending:
        await _safe_edit(callback, "Nenhuma ação pendente para confirmar.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    try:
        perms = await get_bot_permissions(bot, chat_id)
        me = await bot.get_me()
        bot_id = int(getattr(me, "id"))
    except Exception as exc:
        storage.log_event(action="destructive_confirm", result="falhou", detection="direta", surface="callback", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, details=str(exc))
        await _safe_edit(callback, f"Falha ao revalidar permissões: {exc}", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    target_user_id = pending.get("target_user_id")
    target_is_admin = False
    if target_user_id is not None:
        target_is_admin = await _target_admin_status(bot, chat_id, int(target_user_id))
    request = DestructiveActionRequest(
        action=str(pending.get("action")),
        chat_id=chat_id,
        chat_title=title,
        actor_user_id=session.moderator_user_id or session.owner_user_id or 0,
        target_user_id=target_user_id,
        message_id=pending.get("message_id"),
        confirmed=True,
        target_is_admin=target_is_admin,
    )
    result = await execute_destructive_action(bot, request, permissions=perms, bot_user_id=bot_id)
    session.payload.pop("pending_destructive_action", None)
    session.selected_action = None
    await _safe_edit(callback, f"Resultado: {result.result}\n{result.detail}", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _show_ddx(callback: CallbackQuery, session: Any) -> None:
    if not TIGRAO_FSM_DDX_HARD_ENABLED:
        await _safe_edit(callback, "DDX hard indisponível. Ative TIGRAO_FSM_DDX_HARD_ENABLED.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    await _safe_edit(callback, f"DDX hard\n\nGrupo: {title}\nID do grupo: {chat_id}", to_inline_keyboard_markup(ddx_keyboard(session.session_id)))


async def _set_ddx_enabled(callback: CallbackQuery, session: Any, enabled: bool) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    affected = storage.set_ddx_enabled(chat_id=chat_id, enabled=enabled)
    storage.log_event(action="ddx_enabled" if enabled else "ddx_disabled", result="concluido", detection="direta", surface="callback", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, details=f"Filtros atualizados: {affected}")
    await _safe_edit(callback, f"DDX {'ativado' if enabled else 'desativado'}. Filtros atualizados: {affected}", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _prompt_ddx_filter(callback: CallbackQuery, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    session.waiting_for = "ddx_filter_text"
    await _safe_edit(callback, "Envie o texto exato do filtro DDX hard.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _handle_ddx_filter_text(message: Message, session: Any, text: str) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    if not text.strip():
        await message.answer("Filtro vazio não permitido.")
        return
    filter_id = storage.create_ddx_filter(chat_id=chat_id, filter_text=text.strip(), created_by=session.moderator_user_id or session.owner_user_id or 0, enabled=True)
    storage.log_event(action="ddx_filter_add", result="concluido", detection="direta", surface="dm", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, details=f"Filtro #{filter_id}: {text.strip()}")
    session.waiting_for = None
    await message.answer(f"Filtro DDX adicionado. ID: {filter_id}")


async def _list_ddx(callback: CallbackQuery, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    rows = storage.list_ddx_filters(chat_id=chat_id, limit=20)
    if not rows:
        text = "Nenhum filtro DDX encontrado."
    else:
        text = "Filtros DDX\n\n" + "\n".join(f"#{row['id']} — {'ativo' if row.get('enabled') else 'inativo'} — {row.get('filter_text')}" for row in rows)
    await _safe_edit(callback, text, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _prompt_ddx_remove(callback: CallbackQuery, session: Any) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await _safe_edit(callback, error, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
        return
    session.waiting_for = "ddx_remove_id"
    await _safe_edit(callback, "Envie o ID numérico do filtro DDX a remover.", to_inline_keyboard_markup(back_close_keyboard(session.session_id)))


async def _handle_ddx_remove_id(message: Message, session: Any, text: str) -> None:
    chat_id, title, error = _selected_group_or_text(session)
    if error:
        await message.answer(error)
        return
    filter_id = _positive_int(text)
    if filter_id is None:
        await message.answer("Envie um ID de filtro numérico positivo.")
        return
    removed = storage.remove_ddx_filter(chat_id=chat_id, filter_id=filter_id)
    storage.log_event(action="ddx_filter_remove", result="concluido" if removed else "nao_encontrado", detection="direta", surface="dm", chat_id=chat_id, chat_title=title, actor_user_id=session.moderator_user_id or session.owner_user_id, details=f"Filtro removido: {filter_id}; linhas: {removed}")
    session.waiting_for = None
    await message.answer("Filtro removido." if removed else "Filtro não encontrado.")


async def _show_logs(callback: CallbackQuery, session: Any, action: str) -> None:
    prefixes = {
        "log_mod": "mod",
        "log_music": "music",
        "log_use": "use",
        "log_join": "join",
        "log_err": "err",
    }
    rows = storage.list_logs(chat_id=session.selected_chat_id, action_prefix=prefixes.get(action), limit=10)
    text = format_logs(rows)
    await _safe_edit(callback, text, to_inline_keyboard_markup(back_close_keyboard(session.session_id)))
