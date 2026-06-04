from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.config.settings import MODERATOR_IDS, OWNER_ID, SECOND_MODERATOR_ID, THIRD_MODERATOR_ID
from app.security.permissions import has_any_grant, is_root_user as _rbac_is_root_user

__all__ = [
    "OWNER_ID",
    "SECOND_MODERATOR_ID",
    "THIRD_MODERATOR_ID",
    "MODERATOR_IDS",
    "is_owner_user",
    "is_moderator_user",
    "is_owner_private_message",
    "is_owner_callback",
]


def is_owner_user(user_id: int | None) -> bool:
    """True somente para o OWNER/root configurado por ambiente."""
    return _rbac_is_root_user(user_id)


def is_moderator_user(user_id: int | None) -> bool:
    """True para root, moderadores legacy ou usuários com grant RBAC ativo."""
    return bool(user_id and (user_id in MODERATOR_IDS or has_any_grant(user_id)))


def is_owner_private_message(message: Message) -> bool:
    """Autorização de acesso ao painel em DM.

    Nome mantido por estabilidade de API, mas libera qualquer moderador
    autorizado em MODERATOR_IDS.
    """
    return bool(
        message.chat.type == "private"
        and message.from_user
        and is_moderator_user(message.from_user.id)
    )


def is_owner_callback(callback: CallbackQuery) -> bool:
    """Autorização de callbacks do painel para MODERATOR_IDS."""
    return bool(callback.from_user and is_moderator_user(callback.from_user.id))
