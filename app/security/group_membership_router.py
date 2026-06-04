from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from app.moderation_tigrao.storage import remember_group
from app.security.adeus_recovery import mark_rejoin_detected
from app.security.audit import log_audit_event
from app.security.managed_groups import get_managed_group, update_group_status, update_managed_group_title

logger = logging.getLogger(__name__)
router = Router(name="group_membership")


def _status(member: Any) -> str:
    raw = getattr(getattr(member, "status", "unknown"), "value", getattr(member, "status", "unknown"))
    text = str(raw).lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _bool_attr(member: Any, name: str) -> bool | None:
    if not hasattr(member, name):
        return None
    return bool(getattr(member, name))


@router.my_chat_member()
async def track_bot_membership(event: ChatMemberUpdated) -> None:
    """Atualiza estado quando o próprio bot entra/sai/vira admin/perde admin.

    `my_chat_member` é a fonte correta para mudanças de status do bot no chat.
    A UX normal não expõe chat_id; logs/auditoria técnica mantêm o dado interno.
    """
    chat = event.chat
    chat_id = int(chat.id)
    if getattr(chat, "type", None) not in {"group", "supergroup", "channel"}:
        return

    title = getattr(chat, "title", None) or "grupo"
    new_member = event.new_chat_member
    status = _status(new_member)
    remember_group(chat_id, title)

    if get_managed_group(chat_id):
        update_managed_group_title(chat_id, title)

    if status in {"administrator", "creator", "owner"}:
        update_group_status(
            chat_id=chat_id,
            bot_status=status,
            can_delete_messages=_bool_attr(new_member, "can_delete_messages"),
            can_restrict_members=_bool_attr(new_member, "can_restrict_members"),
            can_pin_messages=_bool_attr(new_member, "can_pin_messages"),
            can_manage_tags=_bool_attr(new_member, "can_manage_tags"),
            can_change_info=_bool_attr(new_member, "can_change_info"),
            can_promote_members=_bool_attr(new_member, "can_promote_members"),
            can_invite_users=_bool_attr(new_member, "can_invite_users"),
            can_manage_topics=_bool_attr(new_member, "can_manage_topics"),
            can_manage_video_chats=_bool_attr(new_member, "can_manage_video_chats"),
            last_error=None,
        )
        mark_rejoin_detected(chat_id, title=title, status=status)
    elif status in {"member", "restricted"}:
        update_group_status(chat_id=chat_id, bot_status=status, last_error=None)
        mark_rejoin_detected(chat_id, title=title, status=status)
    elif status in {"left", "kicked"}:
        update_group_status(chat_id=chat_id, bot_status=status, last_error="bot saiu ou foi removido do grupo")
    else:
        update_group_status(chat_id=chat_id, bot_status=status, last_error=None)

    try:
        log_audit_event(
            category="groups",
            action="my_chat_member",
            status="success",
            actor_user_id=getattr(getattr(event, "from_user", None), "id", None),
            chat_id=chat_id,
            payload={"title": title, "bot_status": status},
        )
    except Exception:
        logger.debug("GROUP_MEMBERSHIP_AUDIT_FAILED", exc_info=True)

    logger.warning("BOT_MEMBERSHIP_UPDATED | chat_id=%s | title=%s | status=%s", chat_id, title, status)
