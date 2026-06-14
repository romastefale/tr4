from __future__ import annotations

import logging
from typing import Any

from aiogram.types import Update

from app.fsm_tigrao.context import record_group_message_context

logger = logging.getLogger(__name__)


def _message_from_update(update: Update) -> Any:
    return getattr(update, "message", None) or getattr(update, "edited_message", None)


def record_x9_update_context(update: Update) -> None:
    """Silent group observer used by the private FSM.

    Fase 12D distinction:
    - this function is only the *contextual X9* that feeds private /tmod;
    - the automatic X9/DDX pipeline remains in app.equalizador.ddx and still
      runs after this capture in app.main;
    - therefore existing automatic actions such as auto-delete, event logging
      and private owner alerts are not disabled by the private-FSM migration.

    Fase 12C hardening is preserved: contextual capture only retains context
    for allowed/enabled groups. Unknown groups are ignored unless explicitly
    enabled by configuration or by an authorized private/trigger flow. The
    observer never responds in the group, never shows buttons and never blocks
    dispatch.
    """
    try:
        message = _message_from_update(update)
        record_group_message_context(message, allow_unknown_group=False)
    except Exception:
        logger.debug("X9_UPDATE_CONTEXT_FAILED", exc_info=True)
