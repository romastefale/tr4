from __future__ import annotations

import contextvars
from contextvars import Token
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import SESSION_PERSISTENCE_ENABLED
from app.security.session_store import cleanup_expired_private_sessions, delete_private_session, load_private_session, save_private_session

from app.moderation_tigrao.permissions import MODERATOR_IDS, OWNER_ID

SESSION_NAMESPACE = "btb"
SESSION_TIMEOUT_SECONDS = 30 * 60


@dataclass
class BtbSession:
    owner_id: int = OWNER_ID
    target_username: str | None = None
    group_id: int | None = None
    group_title: str | None = None
    mode: str = "visible"  # visible | silent | dry
    wait_seconds: int = 8
    cleanup: bool = True
    fallback: bool = False
    waiting_for: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _session_to_payload(session: BtbSession) -> dict[str, Any]:
    return {
        "owner_id": session.owner_id,
        "target_username": session.target_username,
        "group_id": session.group_id,
        "group_title": session.group_title,
        "mode": session.mode,
        "wait_seconds": session.wait_seconds,
        "cleanup": session.cleanup,
        "fallback": session.fallback,
        "waiting_for": session.waiting_for,
        "payload": session.payload,
        "updated_at": session.updated_at.isoformat(),
    }


def _session_from_payload(payload: dict[str, Any], *, fallback_user_id: int) -> BtbSession:
    return BtbSession(
        owner_id=int(payload.get("owner_id") or fallback_user_id or OWNER_ID),
        target_username=payload.get("target_username"),
        group_id=payload.get("group_id"),
        group_title=payload.get("group_title"),
        mode=str(payload.get("mode") or "visible"),
        wait_seconds=int(payload.get("wait_seconds") or 8),
        cleanup=bool(payload.get("cleanup", True)),
        fallback=bool(payload.get("fallback", False)),
        waiting_for=payload.get("waiting_for"),
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        updated_at=_parse_datetime(payload.get("updated_at")),
    )


def _persist_session(user_id: int, session: BtbSession) -> None:
    if not SESSION_PERSISTENCE_ENABLED or not is_persistent_user(user_id):
        return
    save_private_session(
        namespace=SESSION_NAMESPACE,
        user_id=int(user_id),
        payload=_session_to_payload(session),
        updated_at=session.updated_at,
        expires_at=session.updated_at + timedelta(seconds=SESSION_TIMEOUT_SECONDS * 2),
    )


def _load_persisted_session(user_id: int) -> BtbSession | None:
    if not SESSION_PERSISTENCE_ENABLED or not is_persistent_user(user_id):
        return None
    payload = load_private_session(namespace=SESSION_NAMESPACE, user_id=int(user_id))
    if not payload:
        return None
    return _session_from_payload(payload, fallback_user_id=user_id)


# Correção do FSM (co-moderação): igual a moderation_tigrao/state.py. Os
# 2 moderadores autorizados podem usar o BTB ao mesmo tempo, então o estado
# é por user_id, propagado via ContextVar setado no início do update (ver
# set_current_user em app/main.py). Cada um tem sua BtbSession isolada.
_sessions: dict[int, BtbSession] = {}

_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "btb_current_user_id", default=None
)


def set_current_user(user_id: int | None) -> Token[int | None]:
    """Define o usuário corrente pro contexto atual e retorna token de reset."""
    return _current_user_id.set(user_id)


def reset_current_user(token: Token[int | None] | None) -> None:
    if token is not None:
        _current_user_id.reset(token)


def current_user_id() -> int | None:
    return _current_user_id.get()


def _current_key() -> int:
    uid = _current_user_id.get()
    return uid if uid is not None else 0


def is_persistent_user(user_id: int | None) -> bool:
    return bool(user_id and user_id in MODERATOR_IDS)


def session_count() -> int:
    return len(_sessions)


def session_user_ids() -> list[int]:
    return sorted(_sessions)


def clear_user_session(user_id: int) -> bool:
    removed_memory = _sessions.pop(int(user_id), None) is not None
    removed_store = delete_private_session(namespace=SESSION_NAMESPACE, user_id=int(user_id)) if SESSION_PERSISTENCE_ENABLED else False
    return bool(removed_memory or removed_store)


def cleanup_expired_sessions(*, max_idle_seconds: int = 30 * 60) -> int:
    now = datetime.now(timezone.utc)
    removed = 0
    for user_id, session in list(_sessions.items()):
        if (now - session.updated_at).total_seconds() > max_idle_seconds:
            del _sessions[user_id]
            removed += 1
    if SESSION_PERSISTENCE_ENABLED:
        cleanup_expired_private_sessions()
    return removed


def session_diagnostics() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for user_id, session in sorted(_sessions.items()):
        rows.append({
            "user_id": user_id,
            "group_id": session.group_id,
            "group_title": session.group_title,
            "target_username": session.target_username,
            "mode": session.mode,
            "waiting_for": session.waiting_for,
            "payload_keys": sorted(session.payload),
            "idle_seconds": int((now - session.updated_at).total_seconds()),
            "updated_at": session.updated_at.isoformat(),
        })
    return {"total": len(rows), "rows": rows}


def get_session() -> BtbSession:
    key = _current_key()
    # Bound de memória: igual a moderation_tigrao/state.py. Só persiste pra
    # moderador autorizado; não-moderador recebe objeto transitório vazio.
    if not is_persistent_user(key):
        return BtbSession(owner_id=key or OWNER_ID)
    session = _sessions.get(key)
    if session is None:
        session = _load_persisted_session(key) or BtbSession(owner_id=key)
        _sessions[key] = session
    return session


def reset_session() -> BtbSession:
    key = _current_key()
    session = BtbSession(owner_id=key or OWNER_ID)
    if is_persistent_user(key):
        _sessions[key] = session
        _persist_session(key, session)
    return session


def clear_waiting() -> None:
    s = get_session()
    s.waiting_for = None
    s.payload = {}
    s.updated_at = datetime.now(timezone.utc)
    _persist_session(_current_key(), s)


def persist_current_session() -> None:
    key = _current_key()
    if key and key in _sessions:
        _sessions[key].updated_at = datetime.now(timezone.utc)
        _persist_session(key, _sessions[key])
