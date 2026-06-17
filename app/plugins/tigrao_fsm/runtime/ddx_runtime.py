"""Runtime DDX hard isolado do Tigrão FSM, ainda não conectado ao webhook."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

RUNTIME_ACTIVE = False

@dataclass(frozen=True, slots=True)
class DDXConfig:
    active: bool = False
    filter_text: str | None = None


async def handle(bot: Any, update: Any, *, config: DDXConfig | None = None, logger: Callable[[dict[str, Any]], Awaitable[None]] | None = None) -> bool:
    config = config or DDXConfig()
    message = getattr(update, "message", update)
    chat = getattr(message, "chat", None)
    if not config.active or getattr(chat, "type", None) not in {"group", "supergroup"}:
        return False
    text = getattr(message, "text", "") or ""
    if config.filter_text and config.filter_text not in text:
        return False
    if hasattr(bot, "delete_message"):
        await bot.delete_message(chat.id, message.message_id)
    if logger is not None:
        await logger({"ato": "ddx_delete", "resultado": "apagado", "onde": "before_dispatch"})
    return True
