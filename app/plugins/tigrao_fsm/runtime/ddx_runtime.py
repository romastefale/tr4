"""Runtime DDX hard isolado do Tigrão FSM."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config.settings import TIGRAO_FSM_DDX_HARD_ENABLED

from .. import storage
from ..permissions import get_bot_permissions


@dataclass(frozen=True, slots=True)
class DDXConfig:
    active: bool = False
    filter_text: str | None = None


def _normalized(value: Any) -> str:
    return str(value or "").casefold().strip()


def _message_from_update(update: Any) -> Any | None:
    return getattr(update, "message", update)


def _chat_type(message: Any) -> str | None:
    return getattr(getattr(message, "chat", None), "type", None)


def _text_or_caption(message: Any) -> str:
    return "\n".join(part for part in [str(getattr(message, "text", "") or ""), str(getattr(message, "caption", "") or "")] if part)


async def _delete_and_log(
    bot: Any,
    message: Any,
    *,
    filter_text: str,
    logger: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> bool:
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    await bot.delete_message(chat.id, message.message_id)
    storage.log_event(
        action="ddx_delete",
        result="apagado",
        detection="direta",
        surface="ddx_pre_dispatch",
        chat_id=int(chat.id),
        chat_title=getattr(chat, "title", None),
        actor_user_id=int(getattr(user, "id")) if getattr(user, "id", None) is not None else None,
        actor_username=getattr(user, "username", None),
        actor_full_name=getattr(user, "full_name", None) or getattr(user, "first_name", None),
        details=f"Filtro acionado: {filter_text}",
        metadata={"message_id": getattr(message, "message_id", None)},
    )
    if logger is not None:
        await logger({"ato": "ddx_delete", "resultado": "apagado", "onde": "before_dispatch", "filtro": filter_text})
    return True


async def handle(
    bot: Any,
    update: Any,
    *,
    config: DDXConfig | None = None,
    permissions: Any | None = None,
    logger: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> bool:
    """Executa DDX hard com negação por padrão.

    Sem configuração explícita ou flag global, a função não apaga nada.
    """
    message = _message_from_update(update)
    if message is None or _chat_type(message) not in {"group", "supergroup"}:
        return False
    chat = getattr(message, "chat", None)
    chat_id = int(getattr(chat, "id"))
    body = _normalized(_text_or_caption(message))
    if not body:
        return False

    if config is not None:
        if config.active is not True:
            return False
        filters = [_normalized(config.filter_text)]
    else:
        if TIGRAO_FSM_DDX_HARD_ENABLED is not True:
            return False
        filters = [_normalized(item) for item in storage.get_enabled_ddx_filters(chat_id=chat_id)]
    filters = [item for item in filters if item]
    if not filters:
        return False

    if permissions is None:
        try:
            permissions = await get_bot_permissions(bot, chat_id)
        except Exception:
            return False
    if getattr(permissions, "can_delete_messages", False) is not True:
        return False

    for filter_text in filters:
        if filter_text in body:
            return await _delete_and_log(bot, message, filter_text=filter_text, logger=logger)
    return False
