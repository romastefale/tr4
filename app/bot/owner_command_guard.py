"""Bloqueio de comandos restritos ao dono do código."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject

from app.config.settings import is_code_owner
from app.services.ops_control import user_id_from_update

logger = logging.getLogger(__name__)

OWNER_ONLY_USER_COMMANDS = frozenset({
    "login",
    "logout",
    "albnow",
    "tcanvas",
    "radiofm",
    "myself",
    "weekfm",
    "monthfm",
})


def _command_from_event(event: TelegramObject) -> str | None:
    message = getattr(event, "message", None) or getattr(event, "edited_message", None)
    if message is None and hasattr(event, "text"):
        message = event
    text_value = getattr(message, "text", None) if message is not None else None
    if not text_value:
        callback = getattr(event, "data", None) or getattr(
            getattr(event, "callback_query", None), "data", None
        )
        if isinstance(callback, str) and callback.startswith("myself:"):
            return "myself"
        return None
    first = str(text_value).strip().split(maxsplit=1)[0]
    if not first.startswith("/"):
        return None
    return first[1:].split("@", 1)[0].strip().lower() or None


class OwnerRestrictedCommandMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = user_id_from_update(event)
        try:
            owner = is_code_owner(user_id)
        except Exception:
            owner = False
        if owner:
            return await handler(event, data)
        command = _command_from_event(event)
        if command in OWNER_ONLY_USER_COMMANDS:
            logger.info(
                "DISPATCHER_UPDATE_DROPPED_OWNER_ONLY_COMMAND user_id=%s command=%s",
                user_id,
                command,
            )
            return None
        return await handler(event, data)


def install_owner_command_guard(dispatcher: Dispatcher) -> None:
    if getattr(dispatcher, "_tr4_owner_command_guard_installed", False):
        return
    dispatcher.update.outer_middleware(OwnerRestrictedCommandMiddleware())
    setattr(dispatcher, "_tr4_owner_command_guard_installed", True)
