"""Objeto do plugin Tigrão FSM isolado.

Etapa 02 prepara a interface final, sem conectar ao dispatcher real do TR4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .permissions import is_private_panel_surface
from .runtime.ddx_runtime import handle as ddx_handle

@dataclass(slots=True)
class TigraoFSMPlugin:
    """Contêiner isolado para montagem futura do Tigrão FSM."""
    mounted: bool = False
    routers: list[Any] = field(default_factory=list)
    current_user_id: int | None = None

    def mount(self, dispatcher: Any) -> None:
        """Prepara routers internos sem incluir no dispatcher global nesta etapa."""
        _ = dispatcher
        self.mounted = True

    async def before_dispatch(self, bot: Any, update: Any) -> bool:
        """Runtime isolado para DDX hard futuro; não conectado ao webhook real."""
        return await ddx_handle(bot, update)

    def set_current_user(self, user_id: int | None) -> None:
        self.current_user_id = int(user_id) if user_id is not None else None

    def register_router_stub(self, router: Any) -> None:
        """Guarda routers para etapa futura sem chamar o dispatcher real."""
        self.routers.append(router)

    async def handle_tigrao_command(self, bot: Any, message: Any, *, authorized: bool) -> bool:
        """Implementa regra DM-only do painel de modo testável e isolado."""
        chat = getattr(message, "chat", None)
        chat_type = getattr(chat, "type", None)
        if is_private_panel_surface(chat_type):
            if authorized and hasattr(message, "answer"):
                await message.answer("Tigrão")
            return True
        if authorized:
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if user_id is not None:
                try:
                    await bot.send_message(user_id, "Tigrão")
                except Exception:
                    return True
        return True
