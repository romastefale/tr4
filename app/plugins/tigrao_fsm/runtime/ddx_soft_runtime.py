"""Stub runtime do Tigrão FSM isolado.

Etapa 01: nenhum hook é conectado ao webhook real.
"""
from __future__ import annotations
from typing import Any

RUNTIME_ACTIVE = False

async def handle(*args: Any, **kwargs: Any) -> bool:
    """Retorna False para indicar que o runtime não processou o update."""
    return False
