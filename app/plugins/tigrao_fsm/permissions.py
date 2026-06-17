"""Permissões isoladas do Tigrão FSM.

Stub da Etapa 01: autorização real será revisada na integração futura.
"""
from __future__ import annotations

from collections.abc import Iterable


def is_authorized_user(user_id: int | None, *, owner_ids: Iterable[int] = (), moderator_ids: Iterable[int] = ()) -> bool:
    if user_id is None:
        return False
    return int(user_id) in {int(v) for v in owner_ids} | {int(v) for v in moderator_ids}


def should_answer_panel_publicly(chat_type: str | None) -> bool:
    """Painel nunca deve responder publicamente em grupo nesta etapa."""
    return chat_type == "private"
