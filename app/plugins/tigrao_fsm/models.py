"""Modelos internos para armazenamento futuro do Tigrão FSM."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

JOIN_REQUEST_TTL = timedelta(hours=2)
USER_CHAT_DM_TTL = timedelta(minutes=5)

@dataclass(slots=True)
class TigraoJoinRequest:
    chat_id: int
    chat_title: str
    user_id: int
    username: str | None
    full_name: str
    user_chat_id: int | None
    bio: str | None
    invite_link: str | None
    request_date: datetime
    received_at: datetime
    expires_at: datetime
    status: str = "pendente"
    processed_at: datetime | None = None
    processed_by: int | None = None
    result_detail: str | None = None

    @classmethod
    def create(cls, **kwargs: Any) -> "TigraoJoinRequest":
        now = kwargs.setdefault("received_at", datetime.now(timezone.utc))
        kwargs.setdefault("expires_at", now + JOIN_REQUEST_TTL)
        return cls(**kwargs)

@dataclass(slots=True)
class TigraoJoinAutoAccept:
    chat_id: int
    chat_title: str
    invite_link: str
    allowed_user_id: int
    allowed_username: str | None
    allowed_full_name: str | None
    created_by_owner_id: int
    created_at: datetime
    expires_at: datetime
    status: str = "aguardando_solicitação"
    approved_at: datetime | None = None
    result_detail: str | None = None

@dataclass(slots=True)
class TigraoLogEntry:
    data: str
    hora: str
    chat_id: int | None = None
    chat_title: str | None = None
    actor_user_id: int | None = None
    actor_username: str | None = None
    actor_full_name: str | None = None
    target_user_id: int | None = None
    target_username: str | None = None
    target_full_name: str | None = None
    ato: str | None = None
    resultado: str | None = None
    deteccao: str | None = None
    onde: str | None = None
    detalhe: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    musica: str = "não detectada"
    artista: str = "não detectado"
    fonte_detectada: str | None = None
