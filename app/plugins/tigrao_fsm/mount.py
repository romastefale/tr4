"""Ponto de montagem futuro do Tigrão FSM.

Não chama dispatcher.include_router nesta etapa.
"""
from __future__ import annotations

from typing import Any
from .plugin import TigraoFSMPlugin


def build_tigrao_fsm_plugin(*, dispatcher: Any | None = None) -> TigraoFSMPlugin:
    """Cria o plugin isolado sem conectá-lo ao dispatcher real."""
    _ = dispatcher
    return TigraoFSMPlugin(mounted=False)
