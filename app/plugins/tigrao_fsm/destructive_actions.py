"""Ações destrutivas guardadas do Tigrão FSM.

Todas as funções negam por padrão e registram log persistente. Nenhuma ação
real deve ser executada sem confirmação explícita e permissão já verificada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import CODE_OWNER_IDS, TIGRAO_FSM_MODERATOR_IDS

from .permissions import TigraoBotPermissions
from . import storage

try:  # aiogram é opcional nos testes estáticos locais.
    from aiogram.types import ChatPermissions as _AiogramChatPermissions
except Exception:  # pragma: no cover
    _AiogramChatPermissions = None

USER_ACTIONS = {"ban", "unban", "mute1h", "mute24h", "muteforever", "unmute"}
DELETE_ACTIONS = {"delmsg"}
ALL_DESTRUCTIVE_ACTIONS = USER_ACTIONS | DELETE_ACTIONS


@dataclass(slots=True)
class DestructiveActionRequest:
    action: str
    chat_id: int
    chat_title: str
    actor_user_id: int
    actor_username: str | None = None
    actor_full_name: str | None = None
    target_user_id: int | None = None
    target_username: str | None = None
    target_full_name: str | None = None
    message_id: int | None = None
    confirmed: bool = False
    target_is_admin: bool = False


@dataclass(slots=True)
class DestructiveActionResult:
    ok: bool
    result: str
    detail: str


def is_protected_target(
    user_id: int | None,
    *,
    bot_user_id: int | None = None,
    target_is_admin: bool = False,
    owner_ids: set[int] | frozenset[int] | None = None,
    moderator_ids: set[int] | frozenset[int] | None = None,
) -> bool:
    if user_id is None:
        return True
    protected = {int(v) for v in (owner_ids if owner_ids is not None else CODE_OWNER_IDS)}
    protected |= {int(v) for v in (moderator_ids if moderator_ids is not None else TIGRAO_FSM_MODERATOR_IDS)}
    if bot_user_id is not None:
        protected.add(int(bot_user_id))
    return int(user_id) in protected or target_is_admin is True


def _mute_permissions() -> Any:
    if _AiogramChatPermissions is not None:
        return _AiogramChatPermissions(can_send_messages=False)
    return {"can_send_messages": False}


def _unmute_permissions() -> Any:
    if _AiogramChatPermissions is not None:
        return _AiogramChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            # Desmutar não deve conceder poderes administrativos ou semiadministrativos.
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )
    return {"can_send_messages": True}


def _until_date_for(action: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if action == "mute1h":
        return now + timedelta(hours=1)
    if action == "mute24h":
        return now + timedelta(hours=24)
    return None


def _required_permission(action: str) -> str:
    if action in USER_ACTIONS:
        return "can_restrict_members"
    if action in DELETE_ACTIONS:
        return "can_delete_messages"
    return "unknown"


def _permission_allowed(action: str, permissions: TigraoBotPermissions) -> bool:
    if not permissions.is_admin:
        return False
    if action in USER_ACTIONS:
        return permissions.can_restrict_members
    if action in DELETE_ACTIONS:
        return permissions.can_delete_messages
    return False


def _log(request: DestructiveActionRequest, *, result: str, detail: str, metadata: dict[str, Any] | None = None) -> None:
    storage.log_event(
        action=f"destructive_{request.action}",
        result=result,
        detection="direta",
        surface="callback",
        chat_id=request.chat_id,
        chat_title=request.chat_title,
        actor_user_id=request.actor_user_id,
        actor_username=request.actor_username,
        actor_full_name=request.actor_full_name,
        target_user_id=request.target_user_id,
        target_username=request.target_username,
        target_full_name=request.target_full_name,
        details=detail,
        metadata={"message_id": request.message_id, **(metadata or {})},
    )


async def execute_destructive_action(
    bot: Any,
    request: DestructiveActionRequest,
    *,
    permissions: TigraoBotPermissions,
    bot_user_id: int | None = None,
) -> DestructiveActionResult:
    """Executa ação destrutiva depois de todas as revalidações.

    A função nunca levanta erro esperado: retorna falha e grava log.
    """
    if request.action not in ALL_DESTRUCTIVE_ACTIONS:
        detail = "Ação desconhecida."
        _log(request, result="bloqueado", detail=detail)
        return DestructiveActionResult(False, "bloqueado", detail)
    if request.confirmed is not True:
        detail = "Ação bloqueada: confirmação explícita ausente."
        _log(request, result="bloqueado_sem_confirmacao", detail=detail)
        return DestructiveActionResult(False, "bloqueado_sem_confirmacao", detail)
    if not _permission_allowed(request.action, permissions):
        detail = f"Ação bloqueada: permissão exigida {_required_permission(request.action)} ausente."
        _log(request, result="bloqueado_sem_permissao", detail=detail)
        return DestructiveActionResult(False, "bloqueado_sem_permissao", detail)
    if request.action in USER_ACTIONS:
        if request.target_user_id is None or request.target_user_id <= 0:
            detail = "Ação bloqueada: ID de usuário inválido."
            _log(request, result="bloqueado_alvo_invalido", detail=detail)
            return DestructiveActionResult(False, "bloqueado_alvo_invalido", detail)
        if is_protected_target(request.target_user_id, bot_user_id=bot_user_id, target_is_admin=request.target_is_admin):
            detail = "Ação bloqueada: alvo protegido."
            _log(request, result="bloqueado_alvo_protegido", detail=detail)
            return DestructiveActionResult(False, "bloqueado_alvo_protegido", detail)
    if request.action == "delmsg" and (request.message_id is None or request.message_id <= 0):
        detail = "Ação bloqueada: ID de mensagem inválido."
        _log(request, result="bloqueado_mensagem_invalida", detail=detail)
        return DestructiveActionResult(False, "bloqueado_mensagem_invalida", detail)

    try:
        if request.action == "ban":
            await bot.ban_chat_member(chat_id=request.chat_id, user_id=request.target_user_id)
        elif request.action == "unban":
            await bot.unban_chat_member(chat_id=request.chat_id, user_id=request.target_user_id)
        elif request.action in {"mute1h", "mute24h", "muteforever"}:
            kwargs: dict[str, Any] = {
                "chat_id": request.chat_id,
                "user_id": request.target_user_id,
                "permissions": _mute_permissions(),
            }
            until_date = _until_date_for(request.action)
            if until_date is not None:
                kwargs["until_date"] = until_date
            await bot.restrict_chat_member(**kwargs)
        elif request.action == "unmute":
            await bot.restrict_chat_member(
                chat_id=request.chat_id,
                user_id=request.target_user_id,
                permissions=_unmute_permissions(),
            )
        elif request.action == "delmsg":
            await bot.delete_message(chat_id=request.chat_id, message_id=request.message_id)
    except Exception as exc:
        detail = f"Falha Telegram: {exc}"
        _log(request, result="falhou", detail=detail)
        return DestructiveActionResult(False, "falhou", detail)

    detail = "Ação executada com sucesso."
    _log(request, result="concluido", detail=detail)
    return DestructiveActionResult(True, "concluido", detail)
