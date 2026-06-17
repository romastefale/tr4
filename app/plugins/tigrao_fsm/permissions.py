"""Permissões e superfície do painel isolado do Tigrão FSM."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


def is_authorized_user(user_id: int | None, *, owner_ids: Iterable[int] = (), moderator_ids: Iterable[int] = ()) -> bool:
    if user_id is None:
        return False
    return int(user_id) in {int(v) for v in owner_ids} | {int(v) for v in moderator_ids}


def is_private_panel_surface(chat_type: str | None) -> bool:
    return chat_type == "private"


@dataclass(frozen=True, slots=True)
class TigraoBotPermissions:
    is_admin: bool = False
    can_delete_messages: bool = False
    can_restrict_members: bool = False
    can_invite_users: bool = False
    can_pin_messages: bool = False
    can_change_info: bool = False
    can_manage_topics: bool = False
    can_manage_tags: bool = False
    can_manage_chat: bool = False

    @property
    def can_manage_user_actions(self) -> bool:
        return self.can_restrict_members

    @property
    def can_manage_links_and_join_approval(self) -> bool:
        return self.can_invite_users

    @property
    def can_delete_link_or_ddx_messages(self) -> bool:
        return self.can_delete_messages


def permissions_from_chat_member(member: Any) -> TigraoBotPermissions:
    status = getattr(member, "status", None)
    status_value = getattr(status, "value", status)
    is_admin = status_value in {"administrator", "creator"}
    return TigraoBotPermissions(
        is_admin=is_admin,
        can_delete_messages=bool(getattr(member, "can_delete_messages", False)),
        can_restrict_members=bool(getattr(member, "can_restrict_members", False)),
        can_invite_users=bool(getattr(member, "can_invite_users", False)),
        can_pin_messages=bool(getattr(member, "can_pin_messages", False)),
        can_change_info=bool(getattr(member, "can_change_info", False)),
        can_manage_topics=bool(getattr(member, "can_manage_topics", False)),
        can_manage_tags=bool(getattr(member, "can_manage_tags", False)),
        can_manage_chat=bool(getattr(member, "can_manage_chat", False)),
    )


async def get_bot_permissions(bot: Any, chat_id: int) -> TigraoBotPermissions:
    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    return permissions_from_chat_member(member)
