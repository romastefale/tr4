"""Objeto público do plugin Tigrão FSM."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime.ddx_runtime import handle as ddx_handle
from .runtime.join_request_runtime import handle as join_request_handle
from .storage import ensure_tables
from .state import set_current_user as set_state_current_user


@dataclass(slots=True)
class TigraoFSMPlugin:
    """Contêiner público para montagem segura do Tigrão FSM no TR4."""

    mounted: bool = False
    routers: list[Any] = field(default_factory=list)
    current_user_id: int | None = None

    def mount(self, dispatcher: Any) -> None:
        """Inclui routers internos no dispatcher recebido uma única vez."""
        if self.mounted:
            return
        ensure_tables()
        from .routers.panel import router

        dispatcher.include_router(router)
        self.routers.append(router)
        self.mounted = True

    async def before_dispatch(self, bot: Any, update: Any) -> bool:
        """Ponte segura para runtimes pré-dispatch do Tigrão FSM."""
        if await join_request_handle(bot, update):
            return True
        return await ddx_handle(bot, update)

    def set_current_user(self, user_id: int | None) -> None:
        self.current_user_id = int(user_id) if user_id is not None else None
        set_state_current_user(self.current_user_id)
