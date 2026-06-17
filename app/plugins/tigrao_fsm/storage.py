"""Storage persistente do Tigrão FSM.

Fase 4: logs, solicitações de entrada e autoaceite por IDs.
Usa o engine SQLite já existente do TR4 e mantém tudo isolado no plugin.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text

from app.db.database import engine

from .models import JOIN_REQUEST_TTL, TigraoJoinAutoAccept, TigraoJoinRequest

PENDING = "pendente"
APPROVED = "aprovado"
DECLINED = "recusado"
FAILED = "falhou"
EXPIRED = "expirado"
WAITING_REQUEST = "aguardando_solicitação"
CANCELLED = "cancelado"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ensure_tables() -> None:
    """Cria as tabelas tigrao_* de forma idempotente."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER,
                chat_title TEXT,
                actor_user_id INTEGER,
                actor_username TEXT,
                actor_full_name TEXT,
                target_user_id INTEGER,
                target_username TEXT,
                target_full_name TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                detection TEXT NOT NULL,
                surface TEXT NOT NULL,
                details TEXT,
                metadata_json TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_logs_chat_created ON tigrao_logs(chat_id, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_logs_action ON tigrao_logs(action)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                user_chat_id INTEGER,
                bio TEXT,
                invite_link TEXT,
                request_date TEXT NOT NULL,
                received_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL,
                processed_at TEXT,
                processed_by INTEGER,
                result_detail TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_join_requests_lookup ON tigrao_join_requests(chat_id, user_id, status, received_at)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_join_auto_accept (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                invite_link TEXT,
                allowed_user_id INTEGER NOT NULL,
                allowed_username TEXT,
                allowed_full_name TEXT,
                created_by_owner_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL,
                approved_at TEXT,
                result_detail TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_join_auto_accept_lookup ON tigrao_join_auto_accept(chat_id, allowed_user_id, status, expires_at)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_ddx_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                filter_text TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_ddx_filters_chat_enabled ON tigrao_ddx_filters(chat_id, enabled)"))


def log_event(
    *,
    action: str,
    result: str,
    detection: str,
    surface: str,
    chat_id: int | None = None,
    chat_title: str | None = None,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_full_name: str | None = None,
    target_user_id: int | None = None,
    target_username: str | None = None,
    target_full_name: str | None = None,
    details: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    ensure_tables()
    created_at = _to_iso(utcnow())
    with engine.begin() as conn:
        result_obj = conn.execute(
            text("""
                INSERT INTO tigrao_logs (
                    created_at, chat_id, chat_title, actor_user_id, actor_username,
                    actor_full_name, target_user_id, target_username, target_full_name,
                    action, result, detection, surface, details, metadata_json
                ) VALUES (
                    :created_at, :chat_id, :chat_title, :actor_user_id, :actor_username,
                    :actor_full_name, :target_user_id, :target_username, :target_full_name,
                    :action, :result, :detection, :surface, :details, :metadata_json
                )
            """),
            {
                "created_at": created_at,
                "chat_id": chat_id,
                "chat_title": chat_title,
                "actor_user_id": actor_user_id,
                "actor_username": actor_username,
                "actor_full_name": actor_full_name,
                "target_user_id": target_user_id,
                "target_username": target_username,
                "target_full_name": target_full_name,
                "action": action,
                "result": result,
                "detection": detection,
                "surface": surface,
                "details": details,
                "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )
        return int(getattr(result_obj, "lastrowid", 0) or 0)


def list_logs(*, chat_id: int | None = None, limit: int = 10, action_prefix: str | None = None) -> list[dict[str, Any]]:
    ensure_tables()
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": int(limit)}
    if chat_id is not None:
        clauses.append("chat_id = :chat_id")
        params["chat_id"] = int(chat_id)
    if action_prefix:
        clauses.append("action LIKE :action_prefix")
        params["action_prefix"] = f"{action_prefix}%"
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with engine.begin() as conn:
        rows = conn.execute(
            text(f"""
                SELECT * FROM tigrao_logs
                {where}
                ORDER BY id DESC
                LIMIT :limit
            """),
            params,
        ).mappings().all()
    return [dict(row) for row in rows]


def save_join_request(request: TigraoJoinRequest) -> int:
    ensure_tables()
    with engine.begin() as conn:
        result_obj = conn.execute(
            text("""
                INSERT INTO tigrao_join_requests (
                    chat_id, chat_title, user_id, username, full_name, user_chat_id, bio,
                    invite_link, request_date, received_at, expires_at, status,
                    processed_at, processed_by, result_detail
                ) VALUES (
                    :chat_id, :chat_title, :user_id, :username, :full_name, :user_chat_id, :bio,
                    :invite_link, :request_date, :received_at, :expires_at, :status,
                    :processed_at, :processed_by, :result_detail
                )
            """),
            {
                "chat_id": int(request.chat_id),
                "chat_title": request.chat_title,
                "user_id": int(request.user_id),
                "username": request.username,
                "full_name": request.full_name,
                "user_chat_id": int(request.user_chat_id) if request.user_chat_id is not None else None,
                "bio": request.bio,
                "invite_link": request.invite_link,
                "request_date": _to_iso(request.request_date),
                "received_at": _to_iso(request.received_at),
                "expires_at": _to_iso(request.expires_at),
                "status": request.status,
                "processed_at": _to_iso(request.processed_at),
                "processed_by": request.processed_by,
                "result_detail": request.result_detail,
            },
        )
        return int(getattr(result_obj, "lastrowid", 0) or 0)


def _request_from_row(row: dict[str, Any]) -> TigraoJoinRequest:
    return TigraoJoinRequest(
        chat_id=int(row["chat_id"]),
        chat_title=row.get("chat_title") or str(row["chat_id"]),
        user_id=int(row["user_id"]),
        username=row.get("username"),
        full_name=row.get("full_name") or "User",
        user_chat_id=int(row["user_chat_id"]) if row.get("user_chat_id") is not None else None,
        bio=row.get("bio"),
        invite_link=row.get("invite_link"),
        request_date=_from_iso(row.get("request_date")) or utcnow(),
        received_at=_from_iso(row.get("received_at")) or utcnow(),
        expires_at=_from_iso(row.get("expires_at")) or utcnow(),
        status=row.get("status") or PENDING,
        processed_at=_from_iso(row.get("processed_at")),
        processed_by=int(row["processed_by"]) if row.get("processed_by") is not None else None,
        result_detail=row.get("result_detail"),
    )


def find_pending_join_request(*, chat_id: int, user_id: int, now: datetime | None = None) -> TigraoJoinRequest | None:
    ensure_tables()
    now = now or utcnow()
    cutoff = now - JOIN_REQUEST_TTL
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT * FROM tigrao_join_requests
                WHERE chat_id=:chat_id AND user_id=:user_id AND status=:status AND received_at>=:cutoff
                ORDER BY id DESC
                LIMIT 1
            """),
            {"chat_id": int(chat_id), "user_id": int(user_id), "status": PENDING, "cutoff": _to_iso(cutoff)},
        ).mappings().first()
    return _request_from_row(dict(row)) if row else None


def list_pending_join_requests(*, chat_id: int, limit: int = 10, now: datetime | None = None) -> list[TigraoJoinRequest]:
    ensure_tables()
    now = now or utcnow()
    cutoff = now - JOIN_REQUEST_TTL
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM tigrao_join_requests
                WHERE chat_id=:chat_id AND status=:status AND received_at>=:cutoff
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"chat_id": int(chat_id), "status": PENDING, "cutoff": _to_iso(cutoff), "limit": int(limit)},
        ).mappings().all()
    return [_request_from_row(dict(row)) for row in rows]


def update_join_request_status(request: TigraoJoinRequest) -> None:
    ensure_tables()
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE tigrao_join_requests
                SET status=:status, processed_at=:processed_at, processed_by=:processed_by, result_detail=:result_detail
                WHERE chat_id=:chat_id AND user_id=:user_id AND request_date=:request_date
            """),
            {
                "status": request.status,
                "processed_at": _to_iso(request.processed_at),
                "processed_by": request.processed_by,
                "result_detail": request.result_detail,
                "chat_id": int(request.chat_id),
                "user_id": int(request.user_id),
                "request_date": _to_iso(request.request_date),
            },
        )


def create_auto_accept_records(
    *,
    chat_id: int,
    chat_title: str,
    invite_link: str,
    user_ids: Iterable[int],
    created_by_owner_id: int,
    created_at: datetime | None = None,
) -> list[TigraoJoinAutoAccept]:
    ensure_tables()
    created_at = created_at or utcnow()
    expires_at = created_at + JOIN_REQUEST_TTL
    records = [
        TigraoJoinAutoAccept(
            chat_id=int(chat_id),
            chat_title=chat_title,
            invite_link=invite_link,
            allowed_user_id=int(user_id),
            allowed_username=None,
            allowed_full_name=None,
            created_by_owner_id=int(created_by_owner_id),
            created_at=created_at,
            expires_at=expires_at,
        )
        for user_id in user_ids
    ]
    with engine.begin() as conn:
        for record in records:
            conn.execute(
                text("""
                    INSERT INTO tigrao_join_auto_accept (
                        chat_id, chat_title, invite_link, allowed_user_id, allowed_username,
                        allowed_full_name, created_by_owner_id, created_at, expires_at,
                        status, approved_at, result_detail
                    ) VALUES (
                        :chat_id, :chat_title, :invite_link, :allowed_user_id, :allowed_username,
                        :allowed_full_name, :created_by_owner_id, :created_at, :expires_at,
                        :status, :approved_at, :result_detail
                    )
                """),
                {
                    "chat_id": record.chat_id,
                    "chat_title": record.chat_title,
                    "invite_link": record.invite_link,
                    "allowed_user_id": record.allowed_user_id,
                    "allowed_username": record.allowed_username,
                    "allowed_full_name": record.allowed_full_name,
                    "created_by_owner_id": record.created_by_owner_id,
                    "created_at": _to_iso(record.created_at),
                    "expires_at": _to_iso(record.expires_at),
                    "status": record.status,
                    "approved_at": _to_iso(record.approved_at),
                    "result_detail": record.result_detail,
                },
            )
    return records


def _auto_from_row(row: dict[str, Any]) -> TigraoJoinAutoAccept:
    return TigraoJoinAutoAccept(
        chat_id=int(row["chat_id"]),
        chat_title=row.get("chat_title") or str(row["chat_id"]),
        invite_link=row.get("invite_link") or "",
        allowed_user_id=int(row["allowed_user_id"]),
        allowed_username=row.get("allowed_username"),
        allowed_full_name=row.get("allowed_full_name"),
        created_by_owner_id=int(row["created_by_owner_id"]),
        created_at=_from_iso(row.get("created_at")) or utcnow(),
        expires_at=_from_iso(row.get("expires_at")) or utcnow(),
        status=row.get("status") or WAITING_REQUEST,
        approved_at=_from_iso(row.get("approved_at")),
        result_detail=row.get("result_detail"),
    )


def get_active_auto_accept(*, chat_id: int, user_id: int, now: datetime | None = None) -> TigraoJoinAutoAccept | None:
    ensure_tables()
    now = now or utcnow()
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT * FROM tigrao_join_auto_accept
                WHERE chat_id=:chat_id AND allowed_user_id=:user_id AND status=:status AND expires_at>=:now
                ORDER BY id DESC
                LIMIT 1
            """),
            {"chat_id": int(chat_id), "user_id": int(user_id), "status": WAITING_REQUEST, "now": _to_iso(now)},
        ).mappings().first()
    return _auto_from_row(dict(row)) if row else None


def update_auto_accept_status(record: TigraoJoinAutoAccept) -> None:
    ensure_tables()
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE tigrao_join_auto_accept
                SET status=:status, approved_at=:approved_at, result_detail=:result_detail
                WHERE chat_id=:chat_id AND allowed_user_id=:allowed_user_id
                  AND created_by_owner_id=:created_by_owner_id AND created_at=:created_at
            """),
            {
                "status": record.status,
                "approved_at": _to_iso(record.approved_at),
                "result_detail": record.result_detail,
                "chat_id": int(record.chat_id),
                "allowed_user_id": int(record.allowed_user_id),
                "created_by_owner_id": int(record.created_by_owner_id),
                "created_at": _to_iso(record.created_at),
            },
        )


def list_auto_accepts(*, chat_id: int, limit: int = 10, now: datetime | None = None) -> list[TigraoJoinAutoAccept]:
    ensure_tables()
    now = now or utcnow()
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM tigrao_join_auto_accept
                WHERE chat_id=:chat_id AND expires_at>=:now
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"chat_id": int(chat_id), "now": _to_iso(now), "limit": int(limit)},
        ).mappings().all()
    return [_auto_from_row(dict(row)) for row in rows]


def create_ddx_filter(*, chat_id: int, filter_text: str, created_by: int, enabled: bool = True) -> int:
    ensure_tables()
    normalized = str(filter_text or "").strip()
    if not normalized:
        raise ValueError("filter_text obrigatório")
    with engine.begin() as conn:
        result_obj = conn.execute(
            text("""
                INSERT INTO tigrao_ddx_filters (chat_id, filter_text, created_by, created_at, enabled)
                VALUES (:chat_id, :filter_text, :created_by, :created_at, :enabled)
            """),
            {
                "chat_id": int(chat_id),
                "filter_text": normalized,
                "created_by": int(created_by),
                "created_at": _to_iso(utcnow()),
                "enabled": 1 if enabled else 0,
            },
        )
        return int(getattr(result_obj, "lastrowid", 0) or 0)


def list_ddx_filters(*, chat_id: int, enabled_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    ensure_tables()
    clauses = ["chat_id=:chat_id"]
    params: dict[str, Any] = {"chat_id": int(chat_id), "limit": int(limit)}
    if enabled_only:
        clauses.append("enabled=1")
    where = " AND ".join(clauses)
    with engine.begin() as conn:
        rows = conn.execute(
            text(f"""
                SELECT * FROM tigrao_ddx_filters
                WHERE {where}
                ORDER BY id DESC
                LIMIT :limit
            """),
            params,
        ).mappings().all()
    return [dict(row) for row in rows]


def get_enabled_ddx_filters(*, chat_id: int) -> list[str]:
    return [str(row.get("filter_text") or "") for row in list_ddx_filters(chat_id=chat_id, enabled_only=True, limit=100) if row.get("filter_text")]


def set_ddx_enabled(*, chat_id: int, enabled: bool) -> int:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE tigrao_ddx_filters SET enabled=:enabled WHERE chat_id=:chat_id"),
            {"enabled": 1 if enabled else 0, "chat_id": int(chat_id)},
        )
        return int(getattr(result, "rowcount", 0) or 0)


def remove_ddx_filter(*, chat_id: int, filter_id: int) -> int:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM tigrao_ddx_filters WHERE chat_id=:chat_id AND id=:filter_id"),
            {"chat_id": int(chat_id), "filter_id": int(filter_id)},
        )
        return int(getattr(result, "rowcount", 0) or 0)
