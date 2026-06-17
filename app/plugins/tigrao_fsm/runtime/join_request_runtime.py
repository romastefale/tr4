"""Runtime de solicitações de entrada do Tigrão FSM."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config.settings import CODE_OWNER_IDS, TIGRAO_FSM_MODERATOR_IDS

from ..models import TigraoJoinRequest
from ..permissions import get_bot_permissions
from ..services import approve_pending_join_request
from .. import storage

logger = logging.getLogger(__name__)


def _full_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    name = " ".join(part for part in (first, last) if part).strip()
    return name or getattr(user, "full_name", None) or "User"


def _dt_from_telegram(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _invite_link_value(invite_link: Any) -> str | None:
    if invite_link is None:
        return None
    for attr in ("invite_link", "link"):
        value = getattr(invite_link, attr, None)
        if value:
            return str(value)
    return str(invite_link) if invite_link else None


def _request_from_update(join_request: Any) -> TigraoJoinRequest:
    chat = getattr(join_request, "chat", None)
    user = getattr(join_request, "from_user", None) or getattr(join_request, "from", None)
    chat_id = int(getattr(chat, "id"))
    user_id = int(getattr(user, "id"))
    request_date = _dt_from_telegram(getattr(join_request, "date", None))
    return TigraoJoinRequest.create(
        chat_id=chat_id,
        chat_title=getattr(chat, "title", None) or str(chat_id),
        user_id=user_id,
        username=getattr(user, "username", None),
        full_name=_full_name(user),
        user_chat_id=int(getattr(join_request, "user_chat_id")) if getattr(join_request, "user_chat_id", None) is not None else None,
        bio=getattr(join_request, "bio", None),
        invite_link=_invite_link_value(getattr(join_request, "invite_link", None)),
        request_date=request_date,
    )


async def _notify_owner(bot: Any, text: str, owner_user_id: int | None) -> None:
    if owner_user_id is None:
        return
    try:
        await bot.send_message(owner_user_id, text)
    except Exception:
        logger.debug("TIGRAO_JOIN_NOTIFY_OWNER_FAILED", exc_info=True)


async def handle(bot: Any, update: Any) -> bool:
    """Processa chat_join_request quando o plugin está habilitado.

    Retorna True para consumir o update de solicitação de entrada, pois a ponte
    do Tigrão já salvou/avaliou o evento e não há fluxo musical legítimo nessa
    superfície.
    """
    join_request = getattr(update, "chat_join_request", None)
    if join_request is None:
        return False

    request = _request_from_update(join_request)
    storage.save_join_request(request)
    storage.log_event(
        action="join_request_received",
        result="pendente",
        detection="direta",
        surface="chat_join_request",
        chat_id=request.chat_id,
        chat_title=request.chat_title,
        actor_user_id=request.user_id,
        actor_username=request.username,
        actor_full_name=request.full_name,
        target_user_id=request.user_id,
        target_username=request.username,
        target_full_name=request.full_name,
        details="Solicitação de entrada recebida e salva por 2h.",
        metadata={"invite_link": request.invite_link, "user_chat_id": request.user_chat_id},
    )

    auto = storage.get_active_auto_accept(chat_id=request.chat_id, user_id=request.user_id)
    if auto is None:
        return True

    try:
        perms = await get_bot_permissions(bot, request.chat_id)
    except Exception:
        logger.debug("TIGRAO_JOIN_PERMISSION_CHECK_FAILED", exc_info=True)
        perms = None
    if perms is None or not perms.is_admin or not perms.can_invite_users:
        detail = "Autoaceite não executado: bot sem can_invite_users no momento da solicitação."
        request.status = storage.FAILED
        request.processed_at = storage.utcnow()
        request.result_detail = detail
        auto.status = storage.FAILED
        auto.result_detail = detail
        storage.update_join_request_status(request)
        storage.update_auto_accept_status(auto)
        storage.log_event(
            action="join_auto_accept",
            result="falhou_sem_permissao",
            detection="direta",
            surface="chat_join_request",
            chat_id=request.chat_id,
            chat_title=request.chat_title,
            actor_user_id=auto.created_by_owner_id,
            target_user_id=request.user_id,
            target_username=request.username,
            target_full_name=request.full_name,
            details=detail,
        )
        return True

    detail = await approve_pending_join_request(
        bot,
        request,
        processed_by=auto.created_by_owner_id,
        autoaccept=True,
        origin="ID autorizado no painel",
    )
    if request.status == "aprovado":
        auto.status = storage.APPROVED
        auto.approved_at = request.processed_at
    else:
        auto.status = storage.FAILED
    auto.result_detail = detail
    storage.update_join_request_status(request)
    storage.update_auto_accept_status(auto)
    storage.log_event(
        action="join_auto_accept",
        result=request.status,
        detection="direta",
        surface="chat_join_request",
        chat_id=request.chat_id,
        chat_title=request.chat_title,
        actor_user_id=auto.created_by_owner_id,
        target_user_id=request.user_id,
        target_username=request.username,
        target_full_name=request.full_name,
        details=detail,
    )
    await _notify_owner(bot, detail, auto.created_by_owner_id)
    return True
