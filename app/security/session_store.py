from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import text

from app.db.database import engine

_INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS private_sessions (
                    namespace TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at DATETIME NOT NULL,
                    expires_at DATETIME,
                    PRIMARY KEY (namespace, user_id)
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_private_sessions_expires ON private_sessions(expires_at);"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS operational_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at DATETIME NOT NULL,
                    expires_at REAL NOT NULL,
                    metadata TEXT
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_operational_locks_expires ON operational_locks(expires_at);"))


def save_private_session(
    *,
    namespace: str,
    user_id: int,
    payload: dict[str, Any],
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    ensure_tables()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO private_sessions (namespace, user_id, payload, updated_at, expires_at)
                VALUES (:namespace, :user_id, :payload, :updated_at, :expires_at)
                ON CONFLICT(namespace, user_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at
                """
            ),
            {
                "namespace": str(namespace),
                "user_id": int(user_id),
                "payload": _json_dump(payload),
                "updated_at": _dt(updated_at),
                "expires_at": _dt(expires_at) if expires_at else None,
            },
        )


def load_private_session(*, namespace: str, user_id: int) -> dict[str, Any] | None:
    ensure_tables()
    now = _dt()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT payload
                  FROM private_sessions
                 WHERE namespace=:namespace
                   AND user_id=:user_id
                   AND (expires_at IS NULL OR expires_at > :now)
                """
            ),
            {"namespace": str(namespace), "user_id": int(user_id), "now": now},
        ).fetchone()
    return _json_load(row[0]) if row else None


def delete_private_session(*, namespace: str, user_id: int) -> bool:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM private_sessions WHERE namespace=:namespace AND user_id=:user_id"),
            {"namespace": str(namespace), "user_id": int(user_id)},
        )
    return bool(result.rowcount)


def cleanup_expired_private_sessions() -> int:
    ensure_tables()
    now = _dt()
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM private_sessions WHERE expires_at IS NOT NULL AND expires_at <= :now"),
            {"now": now},
        )
    return int(result.rowcount or 0)


def list_private_sessions(*, namespace: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    ensure_tables()
    safe_limit = max(1, min(int(limit), 500))
    with engine.begin() as conn:
        if namespace is None:
            rows = conn.execute(
                text("SELECT namespace, user_id, updated_at, expires_at FROM private_sessions ORDER BY updated_at DESC LIMIT :limit"),
                {"limit": safe_limit},
            ).mappings().all()
        else:
            rows = conn.execute(
                text("SELECT namespace, user_id, updated_at, expires_at FROM private_sessions WHERE namespace=:namespace ORDER BY updated_at DESC LIMIT :limit"),
                {"namespace": str(namespace), "limit": safe_limit},
            ).mappings().all()
    return [dict(row) for row in rows]


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    lock_name: str
    owner: str
    expires_at: float | None = None


def acquire_operational_lock(
    lock_name: str,
    *,
    ttl_seconds: int = 90,
    owner: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LockResult:
    ensure_tables()
    now = time.time()
    ttl = max(1, int(ttl_seconds))
    expires_at = now + ttl
    lock_owner = owner or _INSTANCE_ID
    metadata_json = _json_dump(metadata or {})
    with engine.begin() as conn:
        # Remove locks vencidos antes da tentativa. Esta operação é idempotente.
        conn.execute(text("DELETE FROM operational_locks WHERE expires_at <= :now"), {"now": now})
        existing = conn.execute(
            text("SELECT owner, expires_at FROM operational_locks WHERE lock_name=:lock_name"),
            {"lock_name": str(lock_name)},
        ).fetchone()
        if existing and float(existing[1]) > now:
            return LockResult(False, str(lock_name), str(existing[0]), float(existing[1]))
        conn.execute(
            text(
                """
                INSERT INTO operational_locks (lock_name, owner, acquired_at, expires_at, metadata)
                VALUES (:lock_name, :owner, :acquired_at, :expires_at, :metadata)
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner=excluded.owner,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at,
                    metadata=excluded.metadata
                """
            ),
            {
                "lock_name": str(lock_name),
                "owner": lock_owner,
                "acquired_at": _dt(),
                "expires_at": expires_at,
                "metadata": metadata_json,
            },
        )
    return LockResult(True, str(lock_name), lock_owner, expires_at)


def release_operational_lock(lock_name: str, *, owner: str | None = None) -> bool:
    ensure_tables()
    params = {"lock_name": str(lock_name)}
    query = "DELETE FROM operational_locks WHERE lock_name=:lock_name"
    if owner is not None:
        query += " AND owner=:owner"
        params["owner"] = str(owner)
    with engine.begin() as conn:
        result = conn.execute(text(query), params)
    return bool(result.rowcount)


def cleanup_expired_operational_locks() -> int:
    ensure_tables()
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM operational_locks WHERE expires_at <= :now"), {"now": time.time()})
    return int(result.rowcount or 0)


def list_operational_locks() -> list[dict[str, Any]]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT lock_name, owner, acquired_at, expires_at, metadata FROM operational_locks ORDER BY lock_name")
        ).mappings().all()
    return [dict(row) for row in rows]


@contextmanager
def operational_lock(lock_name: str, *, ttl_seconds: int = 90, metadata: dict[str, Any] | None = None) -> Iterator[LockResult]:
    result = acquire_operational_lock(lock_name, ttl_seconds=ttl_seconds, metadata=metadata)
    try:
        yield result
    finally:
        if result.acquired:
            release_operational_lock(lock_name, owner=result.owner)
