"""Objeto do plugin Tigrão FSM isolado.

Etapa 01: não registra routers, não conecta hooks e não altera dispatcher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class TigraoFSMPlugin:
    """Contêiner isolado para montagem futura do Tigrão FSM."""
    mounted: bool = False
    routers: list[Any] = field(default_factory=list)

    async def before_dispatch(self, bot: Any, update: Any) -> bool:
        """Hook futuro para DDX/runtime; sempre inativo na Etapa 01."""
        return False

    def register_router_stub(self, router: Any) -> None:
        """Guarda routers para etapa futura sem chamar dispatcher.include_router."""
        self.routers.append(router)
