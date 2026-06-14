from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.security import TelegramWebAppIdentity


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
    if column not in existing:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_session_tables(db_engine: Engine = default_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_private_sessions (
                    token TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    user_json TEXT NOT NULL,
                    auth_date INTEGER NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    context_json TEXT
                )
                """
            )
        )
        _ensure_column(conn, "eq_private_sessions", "context_json", "context_json TEXT")
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_private_sessions_expires ON eq_private_sessions(expires_at)"))


def save_session(
    *,
    token: str,
    identity: TelegramWebAppIdentity,
    issued_at: int,
    expires_at: int,
    db_engine: Engine = default_engine,
) -> None:
    ensure_session_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_private_sessions (token, telegram_user_id, user_json, auth_date, issued_at, expires_at, updated_at, context_json)
                VALUES (:token, :telegram_user_id, :user_json, :auth_date, :issued_at, :expires_at, :updated_at, :context_json)
                ON CONFLICT(token) DO UPDATE SET
                    telegram_user_id=excluded.telegram_user_id,
                    user_json=excluded.user_json,
                    auth_date=excluded.auth_date,
                    issued_at=excluded.issued_at,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at,
                    context_json=excluded.context_json
                """
            ),
            {
                "token": str(token),
                "telegram_user_id": int(identity.user_id),
                "user_json": json.dumps(identity.user, ensure_ascii=False, separators=(",", ":")),
                "auth_date": int(identity.auth_date),
                "issued_at": int(issued_at),
                "expires_at": int(expires_at),
                "updated_at": _now_iso(),
                "context_json": json.dumps({
                    "raw_init_data": identity.raw_init_data,
                    "chat": identity.chat,
                    "chat_type": identity.chat_type,
                    "chat_instance": identity.chat_instance,
                    "start_param": identity.start_param,
                }, ensure_ascii=False, separators=(",", ":")),
            },
        )


def load_session(token: str, *, db_engine: Engine = default_engine) -> tuple[TelegramWebAppIdentity, int, int] | None:
    ensure_session_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT telegram_user_id, user_json, auth_date, issued_at, expires_at FROM eq_private_sessions WHERE token=:token LIMIT 1"),
            {"token": str(token)},
        ).mappings().first()
    if not row:
        return None
    try:
        user = json.loads(str(row["user_json"] or "{}"))
    except json.JSONDecodeError:
        user = {"id": int(row["telegram_user_id"])}
    try:
        context = json.loads(str(row.get("context_json") or "{}"))
    except json.JSONDecodeError:
        context = {}
    identity = TelegramWebAppIdentity(
        user_id=int(row["telegram_user_id"]),
        user=user,
        auth_date=int(row["auth_date"]),
        raw_init_data=dict(context.get("raw_init_data") or {}),
        chat=context.get("chat") if isinstance(context.get("chat"), dict) else None,
        chat_type=str(context.get("chat_type") or ""),
        chat_instance=str(context.get("chat_instance") or ""),
        start_param=str(context.get("start_param") or ""),
    )
    return identity, int(row["issued_at"]), int(row["expires_at"])


def delete_session(token: str, *, db_engine: Engine = default_engine) -> None:
    ensure_session_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM eq_private_sessions WHERE token=:token"), {"token": str(token)})


def cleanup_expired_sessions(*, now_ts: int, db_engine: Engine = default_engine, grace_seconds: int = 0) -> int:
    ensure_session_tables(db_engine)
    delete_before = int(now_ts) - max(0, int(grace_seconds or 0))
    with db_engine.begin() as conn:
        result = conn.execute(text("DELETE FROM eq_private_sessions WHERE expires_at <= :delete_before"), {"delete_before": delete_before})
    return int(getattr(result, "rowcount", 0) or 0)


def session_store_status(*, now_ts: int, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_session_tables(db_engine)
    with db_engine.begin() as conn:
        total = int(conn.execute(text("SELECT COUNT(*) FROM eq_private_sessions")).scalar() or 0)
        active = int(conn.execute(text("SELECT COUNT(*) FROM eq_private_sessions WHERE expires_at > :now_ts"), {"now_ts": int(now_ts)}).scalar() or 0)
    return {"total": total, "ativas": active, "expiradas": max(0, total - active)}
