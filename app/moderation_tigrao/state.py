from __future__ import annotations

import contextvars
from contextvars import Token
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import SESSION_PERSISTENCE_ENABLED
from app.security.session_store import cleanup_expired_private_sessions, delete_private_session, load_private_session, save_private_session

from app.moderation_tigrao.permissions import MODERATOR_IDS, OWNER_ID
from app.security.permissions import has_any_grant, is_root_user


# Sprint 7 (T01): se o owner abre um fluxo "envie user_id" / "envie texto"
# e abandona, o waiting_for fica grudado. Mensagem comum mandada horas
# depois vira input do fluxo antigo (risco real: colar algo aleatório
# vira tentativa de ban). 15min cobre uso natural sem ser intrusivo.
SESSION_TIMEOUT_SECONDS = 15 * 60
SESSION_NAMESPACE = "tigrao"


@dataclass
class TigrãoSession:
    owner_id: int = OWNER_ID
    selected_chat_id: int | None = None
    selected_group_title: str | None = None
    selected_action: str | None = None
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


def _session_to_payload(session: TigrãoSession) -> dict[str, Any]:
    return {
        "owner_id": session.owner_id,
        "selected_chat_id": session.selected_chat_id,
        "selected_group_title": session.selected_group_title,
        "selected_action": session.selected_action,
        "waiting_for": session.waiting_for,
        "payload": session.payload,
        "updated_at": session.updated_at.isoformat(),
    }


def _session_from_payload(payload: dict[str, Any], *, fallback_user_id: int) -> TigrãoSession:
    return TigrãoSession(
        owner_id=int(payload.get("owner_id") or fallback_user_id or OWNER_ID),
        selected_chat_id=payload.get("selected_chat_id"),
        selected_group_title=payload.get("selected_group_title"),
        selected_action=payload.get("selected_action"),
        waiting_for=payload.get("waiting_for"),
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        updated_at=_parse_datetime(payload.get("updated_at")),
    )


def _persist_session(user_id: int, session: TigrãoSession) -> None:
    if not SESSION_PERSISTENCE_ENABLED or not is_persistent_user(user_id):
        return
    save_private_session(
        namespace=SESSION_NAMESPACE,
        user_id=int(user_id),
        payload=_session_to_payload(session),
        updated_at=session.updated_at,
        expires_at=session.updated_at + timedelta(seconds=SESSION_TIMEOUT_SECONDS * 4),
    )


def _load_persisted_session(user_id: int) -> TigrãoSession | None:
    if not SESSION_PERSISTENCE_ENABLED or not is_persistent_user(user_id):
        return None
    payload = load_private_session(namespace=SESSION_NAMESPACE, user_id=int(user_id))
    if not payload:
        return None
    return _session_from_payload(payload, fallback_user_id=user_id)


# Correção do FSM (co-moderação): antes o estado era um singleton global,
# válido só porque um único humano (OWNER) usava o /tigrao. Agora há 2
# moderadores autorizados que podem operar SIMULTANEAMENTE — se
# compartilhassem o mesmo singleton, o "selecionar grupo" / "aguardando
# user_id" de um sobrescreveria o do outro (state leak real).
#
# Solução: uma sessão por user_id. O user_id corrente é propagado por um
# ContextVar setado no início do processamento do update (ver
# set_current_user em app/main.py), antes dos handlers diretos e do
# dispatcher. Cada handler/asyncio task herda o contexto, então
# get_session() devolve a sessão certa sem precisar passar user_id em
# todas as ~70 chamadas.
_sessions: dict[int, TigrãoSession] = {}

_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tigrao_current_user_id", default=None
)


def set_current_user(user_id: int | None) -> Token[int | None]:
    """Define o usuário corrente pro contexto atual e retorna token de reset.

    Chamado no início do processamento de cada update. Na Fase 10G o token
    deve ser resetado no `finally` do webhook para impedir vazamento de
    contexto entre updates processados pela mesma task/worker.
    """
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
    if not user_id:
        return False
    return bool(user_id in MODERATOR_IDS or is_root_user(user_id) or has_any_grant(user_id))


def session_count() -> int:
    return len(_sessions)


def session_user_ids() -> list[int]:
    return sorted(_sessions)


def clear_user_session(user_id: int) -> bool:
    removed_memory = _sessions.pop(int(user_id), None) is not None
    removed_store = delete_private_session(namespace=SESSION_NAMESPACE, user_id=int(user_id)) if SESSION_PERSISTENCE_ENABLED else False
    return bool(removed_memory or removed_store)


def cleanup_expired_sessions(*, max_idle_seconds: int = SESSION_TIMEOUT_SECONDS * 2) -> int:
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
        idle_seconds = int((now - session.updated_at).total_seconds())
        rows.append({
            "user_id": user_id,
            "selected_chat_id": session.selected_chat_id,
            "selected_group_title": session.selected_group_title,
            "selected_action": session.selected_action,
            "waiting_for": session.waiting_for,
            "payload_keys": sorted(session.payload),
            "idle_seconds": idle_seconds,
            "updated_at": session.updated_at.isoformat(),
        })
    return {"total": len(rows), "rows": rows}


def get_session() -> TigrãoSession:
    key = _current_key()
    # Bound de memória: só persiste sessão pra moderador autorizado.
    # Fase 4: além dos MODERATOR_IDS legados, usuários com grant RBAC
    # ativo precisam de sessão persistente para navegar no painel. Tráfego
    # público sem grant continua recebendo sessão transitória e não cresce
    # _sessions sem limite.
    if not is_persistent_user(key):
        return TigrãoSession(owner_id=key or OWNER_ID)
    session = _sessions.get(key)
    if session is None:
        session = _load_persisted_session(key) or TigrãoSession(owner_id=key)
        _sessions[key] = session
    return session


def reset_session() -> TigrãoSession:
    key = _current_key()
    session = TigrãoSession(owner_id=key or OWNER_ID)
    if is_persistent_user(key):
        _sessions[key] = session
        _persist_session(key, session)
    return session


def set_selected_group(chat_id: int, title: str | None = None) -> TigrãoSession:
    session = get_session()
    session.selected_chat_id = chat_id
    session.selected_group_title = title or str(chat_id)
    session.selected_action = None
    session.waiting_for = None
    session.payload = {}
    session.updated_at = datetime.now(timezone.utc)
    _persist_session(_current_key(), session)
    return session


def set_action(action: str, waiting_for: str | None = None, **payload: Any) -> TigrãoSession:
    session = get_session()
    session.selected_action = action
    session.waiting_for = waiting_for
    session.payload = payload
    session.updated_at = datetime.now(timezone.utc)
    _persist_session(_current_key(), session)
    return session


def clear_action() -> TigrãoSession:
    session = get_session()
    session.selected_action = None
    session.waiting_for = None
    session.payload = {}
    session.updated_at = datetime.now(timezone.utc)
    _persist_session(_current_key(), session)
    return session


def persist_current_session() -> None:
    key = _current_key()
    if key and key in _sessions:
        _sessions[key].updated_at = datetime.now(timezone.utc)
        _persist_session(key, _sessions[key])


def is_waiting_expired(now: datetime | None = None) -> bool:
    """Sprint 7 (T01): True se há waiting_for ativo e expirou (15min).

    Sem waiting_for ativo retorna False (não há fluxo pra expirar).
    """
    session = get_session()
    if session.waiting_for is None:
        return False
    current = now or datetime.now(timezone.utc)
    return (current - session.updated_at) > timedelta(seconds=SESSION_TIMEOUT_SECONDS)


def touch_session() -> TigrãoSession:
    """Sprint 7 (T01-fix): atualiza updated_at sem mexer em waiting_for/payload.

    Use em transitions internas que mudam `waiting_for` direto (não via
    set_action). Garante que `is_waiting_expired()` mede inatividade real
    do usuário, não tempo desde o início do fluxo.
    """
    session = get_session()
    session.updated_at = datetime.now(timezone.utc)
    _persist_session(_current_key(), session)
    return session


def consume_if_expired() -> bool:
    """Sprint 7 (T01): se o fluxo waiting está expirado, limpa e retorna True.

    Callers usam pra abortar o handler com mensagem de "sessão expirada":
        if consume_if_expired():
            await message.answer("Sessão expirada. Recomece em /tigrao.")
            return

    Sprint 7 (T01-fix2, architect): quando o fluxo NÃO expirou e há
    waiting_for ativo, renova updated_at automaticamente. Assim qualquer
    tentativa de input (inclusive inválida que faz retry no mesmo state)
    conta como atividade real do owner — não só transitions completas.
    """
    if is_waiting_expired():
        clear_action()
        return True
    session = get_session()
    if session.waiting_for is not None:
        session.updated_at = datetime.now(timezone.utc)
        _persist_session(_current_key(), session)
    return False
