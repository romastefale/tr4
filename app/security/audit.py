from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    actor_user_id INTEGER,
                    chat_id INTEGER,
                    target_user_id INTEGER,
                    target_message_id INTEGER,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    payload_json TEXT,
                    created_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_events_actor_user_id ON audit_events(actor_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_events_chat_id ON audit_events(chat_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_events_category ON audit_events(category)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events(created_at)"))


def log_audit_event(
    *,
    category: str,
    action: str,
    status: str,
    actor_user_id: int | None = None,
    chat_id: int | None = None,
    target_user_id: int | None = None,
    target_message_id: int | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Registra evento auditável de segurança/moderação/governança.

    Não envia mensagem ao usuário nem levanta exceção por falha de negócio do
    Telegram. É uma trilha local SQLite usada para reconstruir quem fez o quê.
    """
    ensure_tables()
    event_id = uuid.uuid4().hex
    payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO audit_events (
                    event_id, actor_user_id, chat_id, target_user_id,
                    target_message_id, category, action, status, reason,
                    payload_json, created_at
                ) VALUES (
                    :event_id, :actor_user_id, :chat_id, :target_user_id,
                    :target_message_id, :category, :action, :status, :reason,
                    :payload_json, :created_at
                )
                """
            ),
            {
                "event_id": event_id,
                "actor_user_id": actor_user_id,
                "chat_id": chat_id,
                "target_user_id": target_user_id,
                "target_message_id": target_message_id,
                "category": category,
                "action": action,
                "status": status,
                "reason": reason,
                "payload_json": payload_json,
                "created_at": utcnow(),
            },
        )
    return event_id


def list_recent_events(limit: int = 20, category: str | None = None) -> list[dict]:
    ensure_tables()
    limit = max(1, min(int(limit), 100))
    with engine.begin() as conn:
        if category:
            rows = conn.execute(
                text(
                    """
                    SELECT id, event_id, actor_user_id, chat_id, target_user_id,
                           target_message_id, category, action, status, reason,
                           payload_json, created_at
                    FROM audit_events
                    WHERE category=:category
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"category": category, "limit": limit},
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT id, event_id, actor_user_id, chat_id, target_user_id,
                           target_message_id, category, action, status, reason,
                           payload_json, created_at
                    FROM audit_events
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
    return [dict(row) for row in rows]



def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def export_audit_events_jsonl(*, limit: int = 1000, category: str | None = None) -> bytes:
    """Exporta eventos de auditoria em JSONL UTF-8 para uso Owner-only.

    Não altera a base. O limite protege contra payloads muito grandes no Telegram.
    """
    ensure_tables()
    safe_limit = max(1, min(int(limit), 5000))
    with engine.begin() as conn:
        if category:
            rows = conn.execute(
                text(
                    """
                    SELECT id, event_id, actor_user_id, chat_id, target_user_id,
                           target_message_id, category, action, status, reason,
                           payload_json, created_at
                    FROM audit_events
                    WHERE category=:category
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"category": category, "limit": safe_limit},
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT id, event_id, actor_user_id, chat_id, target_user_id,
                           target_message_id, category, action, status, reason,
                           payload_json, created_at
                    FROM audit_events
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": safe_limit},
            ).mappings().all()
    lines: list[str] = []
    for row in rows:
        data = dict(row)
        data["payload"] = _json_load(data.pop("payload_json", None))
        lines.append(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str))
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def cleanup_audit_events_older_than(days: int, *, keep_categories: tuple[str, ...] = ()) -> int:
    """Remove eventos antigos de auditoria.

    `keep_categories` preserva categorias sensíveis mesmo antigas. Use apenas via
    fluxo Owner-only e com export anterior quando necessário.
    """
    ensure_tables()
    safe_days = max(1, int(days))
    cutoff = datetime.fromtimestamp(utcnow().timestamp() - safe_days * 86400, tz=timezone.utc).isoformat()
    with engine.begin() as conn:
        if keep_categories:
            placeholders = ", ".join(f":cat{i}" for i, _ in enumerate(keep_categories))
            params: dict[str, Any] = {"cutoff": cutoff}
            params.update({f"cat{i}": cat for i, cat in enumerate(keep_categories)})
            res = conn.execute(
                text(f"DELETE FROM audit_events WHERE created_at < :cutoff AND category NOT IN ({placeholders})"),
                params,
            )
        else:
            res = conn.execute(text("DELETE FROM audit_events WHERE created_at < :cutoff"), {"cutoff": cutoff})
    return int(res.rowcount or 0)
