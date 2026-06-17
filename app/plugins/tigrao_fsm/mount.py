"""Ponto de montagem futuro do Tigrão FSM.

Não conecta o plugin ao dispatcher real nesta etapa.
"""
from __future__ import annotations

from typing import Any
from .plugin import TigraoFSMPlugin


def build_tigrao_fsm_plugin(*, dispatcher: Any | None = None) -> TigraoFSMPlugin:
    plugin = TigraoFSMPlugin(mounted=False)
    if dispatcher is not None:
        plugin.mount(dispatcher)
    return plugin
