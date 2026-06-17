"""Runtime DDX hard isolado do Tigrão FSM, ainda não conectado ao webhook."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

RUNTIME_ACTIVE = False

@dataclass(frozen=True, slots=True)
class DDXConfig:
    active: bool = False
    filter_text: str | None = None


def _normalized(value: Any) -> str:
    return str(value or "").casefold().strip()


async def handle(
    bot: Any,
    update: Any,
    *,
    config: DDXConfig | None = None,
    permissions: Any | None = None,
    logger: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> bool:
    config = config or DDXConfig()
    if config.active is not True:
        return False
    filter_text = _normalized(config.filter_text)
    if not filter_text:
        return False
    if permissions is None or getattr(permissions, "can_delete_messages", False) is not True:
        return False

    message = getattr(update, "message", update)
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) not in {"group", "supergroup"}:
        return False

    text = _normalized(getattr(message, "text", None))
    caption = _normalized(getattr(message, "caption", None))
    if filter_text not in text and filter_text not in caption:
        return False

    if hasattr(bot, "delete_message"):
        await bot.delete_message(chat.id, message.message_id)
    if logger is not None:
        await logger({"ato": "ddx_delete", "resultado": "apagado", "onde": "before_dispatch"})
    return True
