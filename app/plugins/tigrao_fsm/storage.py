"""Storage persistente do Tigrão FSM."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine

from .models import JOIN_REQUEST_TTL, TigraoJoinAutoAccept, TigraoJoinRequest, TigraoLogEntry

AUTO_ACCEPT_TTL = timedelta(hours=2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def ensure_storage() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME NOT NULL,
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
                detection TEXT,
                surface TEXT,
                details TEXT,
                metadata_json TEXT
            )
        """))
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
                request_date DATETIME,
                received_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                status TEXT NOT NULL,
                processed_at DATETIME,
                processed_by INTEGER,
                result_detail TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_join_requests_chat_user_status ON tigrao_join_requests(chat_id, user_id, status)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tigrao_join_auto_accept (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                invite_link TEXT NOT NULL,
                allowed_user_id INTEGER NOT NULL,
                allowed_username TEXT,
                allowed_full_name TEXT,
                created_by_owner_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                status TEXT NOT NULL,
                approved_at DATETIME,
                result_detail TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tigrao_auto_chat_user_status ON tigrao_join_auto_accept(chat_id, allowed_user_id, status)"))


def ensure_storage_stub() -> bool:
    ensure_storage()
    return True


def log_event(**kwargs: Any) -> None:
    ensure_storage()
    created_at = kwargs.pop("created_at", utcnow())
    metadata = kwargs.pop("metadata_json", None)
    if metadata is not None and not isinstance(metadata, str):
        metadata = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tigrao_logs (created_at, chat_id, chat_title, actor_user_id, actor_username, actor_full_name,
            target_user_id, target_username, target_full_name, action, result, detection, surface, details, metadata_json)
            VALUES (:created_at, :chat_id, :chat_title, :actor_user_id, :actor_username, :actor_full_name,
            :target_user_id, :target_username, :target_full_name, :action, :result, :detection, :surface, :details, :metadata_json)
        """), {"created_at": _iso(created_at), **{k: kwargs.get(k) for k in ["chat_id","chat_title","actor_user_id","actor_username","actor_full_name","target_user_id","target_username","target_full_name","action","result","detection","surface","details"]}, "metadata_json": metadata})


def save_join_request(req: TigraoJoinRequest) -> None:
    ensure_storage()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tigrao_join_requests (chat_id, chat_title, user_id, username, full_name, user_chat_id, bio, invite_link,
            request_date, received_at, expires_at, status, processed_at, processed_by, result_detail)
            VALUES (:chat_id, :chat_title, :user_id, :username, :full_name, :user_chat_id, :bio, :invite_link,
            :request_date, :received_at, :expires_at, :status, :processed_at, :processed_by, :result_detail)
        """), {**asdict(req), "request_date": _iso(req.request_date), "received_at": _iso(req.received_at), "expires_at": _iso(req.expires_at), "processed_at": _iso(req.processed_at)})


def _req(row: Any) -> TigraoJoinRequest:
    m = dict(row)
    for k in ("request_date","received_at","expires_at","processed_at"):
        m[k] = _dt(m.get(k))
    m.pop("id", None)
    return TigraoJoinRequest(**m)


def find_persistent_pending_join_request(*, chat_id: int, user_id: int, now: datetime | None = None) -> TigraoJoinRequest | None:
    ensure_storage(); now = now or utcnow(); cutoff = now - JOIN_REQUEST_TTL
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM tigrao_join_requests WHERE chat_id=:chat_id AND user_id=:user_id AND status='pendente' AND received_at>=:cutoff ORDER BY received_at DESC LIMIT 1"), {"chat_id": chat_id, "user_id": user_id, "cutoff": _iso(cutoff)}).mappings().first()
    return _req(row) if row else None


def update_join_request_status(*, chat_id:int, user_id:int, status:str, processed_by:int|None=None, result_detail:str|None=None, processed_at:datetime|None=None) -> None:
    ensure_storage(); processed_at = processed_at or utcnow()
    with engine.begin() as conn:
        conn.execute(text("UPDATE tigrao_join_requests SET status=:status, processed_at=:processed_at, processed_by=:processed_by, result_detail=:result_detail WHERE chat_id=:chat_id AND user_id=:user_id AND status='pendente'"), locals())


def save_auto_accepts(*, chat_id:int, chat_title:str, invite_link:str, user_ids:list[int], created_by_owner_id:int, now:datetime|None=None) -> int:
    ensure_storage(); now = now or utcnow(); expires_at = now + AUTO_ACCEPT_TTL
    with engine.begin() as conn:
        for uid in user_ids:
            conn.execute(text("""
                INSERT INTO tigrao_join_auto_accept (chat_id, chat_title, invite_link, allowed_user_id, allowed_username, allowed_full_name,
                created_by_owner_id, created_at, expires_at, status, approved_at, result_detail)
                VALUES (:chat_id, :chat_title, :invite_link, :uid, NULL, NULL, :created_by_owner_id, :created_at, :expires_at, 'aguardando_solicitação', NULL, NULL)
            """), {"chat_id":chat_id,"chat_title":chat_title,"invite_link":invite_link,"uid":uid,"created_by_owner_id":created_by_owner_id,"created_at":_iso(now),"expires_at":_iso(expires_at)})
    return len(user_ids)


def active_auto_accept(*, chat_id:int, user_id:int, now:datetime|None=None) -> dict[str, Any] | None:
    ensure_storage(); now = now or utcnow()
    with engine.begin() as conn:
        return conn.execute(text("SELECT * FROM tigrao_join_auto_accept WHERE chat_id=:chat_id AND allowed_user_id=:user_id AND status='aguardando_solicitação' AND expires_at>=:now ORDER BY created_at DESC LIMIT 1"), {"chat_id":chat_id,"user_id":user_id,"now":_iso(now)}).mappings().first()


def mark_auto_accept_approved(*, row_id:int, result_detail:str, approved_at:datetime|None=None) -> None:
    ensure_storage(); approved_at = approved_at or utcnow()
    with engine.begin() as conn:
        conn.execute(text("UPDATE tigrao_join_auto_accept SET status='aprovado', approved_at=:approved_at, result_detail=:result_detail WHERE id=:row_id"), {"approved_at":_iso(approved_at),"result_detail":result_detail,"row_id":row_id})


def recent_logs(category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    ensure_storage()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM tigrao_logs ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]
