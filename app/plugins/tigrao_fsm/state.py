"""FSM própria e isolada do Tigrão.

Stub estrutural da Etapa 01: não usa aiogram.fsm e não é conectado ao TR4.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

SESSION_TIMEOUT_MINUTES = 15
SESSION_TIMEOUT = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
_current_user_id: ContextVar[int | None] = ContextVar("tigrao_fsm_current_user_id", default=None)
_sessions: dict[str, "TigraoSession"] = {}

@dataclass(slots=True)
class TigraoSession:
    """Sessão manual do painel Tigrão, preservando a FSM própria do TR3."""
    session_id: str
    owner_user_id: int | None = None
    moderator_user_id: int | None = None
    selected_chat_id: int | None = None
    selected_group_title: str | None = None
    selected_action: str | None = None
    waiting_for: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + SESSION_TIMEOUT)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
        self.expires_at = self.updated_at + SESSION_TIMEOUT

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


def set_current_user(user_id: int | None) -> None:
    _current_user_id.set(user_id)


def create_session(*, owner_user_id: int | None = None, moderator_user_id: int | None = None) -> TigraoSession:
    sid = uuid4().hex[:12]
    session = TigraoSession(session_id=sid, owner_user_id=owner_user_id, moderator_user_id=moderator_user_id)
    _sessions[sid] = session
    return session


def get_session(session_id: str) -> TigraoSession | None:
    session = _sessions.get(session_id)
    if session and session.expired:
        _sessions.pop(session_id, None)
        return None
    if session:
        session.touch()
    return session


def close_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def get_user_session(user_id: int | None) -> TigraoSession | None:
    if user_id is None:
        return None
    for sid in list(_sessions):
        session = get_session(sid)
        if session is None:
            continue
        owner = session.moderator_user_id or session.owner_user_id
        if owner == int(user_id):
            return session
    return None
