from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.db.database import engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def _json_dump(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _hash_payload(value: dict[str, Any] | None) -> str:
    return hashlib.sha256(_json_dump(value).encode("utf-8")).hexdigest()


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS critical_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL UNIQUE,
                    operation_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor_user_id INTEGER,
                    chat_id INTEGER,
                    target_user_id INTEGER,
                    lock_name TEXT,
                    intent_hash TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    result_json TEXT,
                    reason TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_critical_operations_created ON critical_operations(created_at);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_critical_operations_key ON critical_operations(operation_key);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_critical_operations_status ON critical_operations(status);"))


def begin_critical_operation(
    *,
    category: str,
    action: str,
    operation_key: str,
    actor_user_id: int | None = None,
    chat_id: int | None = None,
    target_user_id: int | None = None,
    lock_name: str | None = None,
    intent: dict[str, Any] | None = None,
) -> str:
    ensure_tables()
    operation_id = uuid.uuid4().hex
    now = _dt()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO critical_operations (
                    operation_id, operation_key, category, action, status,
                    actor_user_id, chat_id, target_user_id, lock_name,
                    intent_hash, intent_json, result_json, reason, created_at, updated_at
                ) VALUES (
                    :operation_id, :operation_key, :category, :action, 'intent',
                    :actor_user_id, :chat_id, :target_user_id, :lock_name,
                    :intent_hash, :intent_json, NULL, NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "operation_id": operation_id,
                "operation_key": str(operation_key),
                "category": str(category),
                "action": str(action),
                "actor_user_id": int(actor_user_id) if actor_user_id is not None else None,
                "chat_id": int(chat_id) if chat_id is not None else None,
                "target_user_id": int(target_user_id) if target_user_id is not None else None,
                "lock_name": str(lock_name) if lock_name else None,
                "intent_hash": _hash_payload(intent),
                "intent_json": _json_dump(intent),
                "created_at": now,
                "updated_at": now,
            },
        )
    return operation_id


def finish_critical_operation(
    operation_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    reason: str | None = None,
) -> bool:
    ensure_tables()
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                UPDATE critical_operations
                   SET status=:status,
                       result_json=:result_json,
                       reason=:reason,
                       updated_at=:updated_at
                 WHERE operation_id=:operation_id
                """
            ),
            {
                "operation_id": str(operation_id),
                "status": str(status),
                "result_json": _json_dump(result),
                "reason": reason,
                "updated_at": _dt(),
            },
        )
    return bool(res.rowcount)


def get_critical_operation(operation_id: str) -> dict[str, Any] | None:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM critical_operations WHERE operation_id=:operation_id"),
            {"operation_id": str(operation_id)},
        ).mappings().first()
    if not row:
        return None
    data = dict(row)
    data["intent"] = _json_load(data.pop("intent_json", None))
    data["result"] = _json_load(data.pop("result_json", None))
    return data


def list_critical_operations(*, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    ensure_tables()
    safe_limit = max(1, min(int(limit), 100))
    with engine.begin() as conn:
        if status:
            rows = conn.execute(
                text("SELECT * FROM critical_operations WHERE status=:status ORDER BY id DESC LIMIT :limit"),
                {"status": str(status), "limit": safe_limit},
            ).mappings().all()
        else:
            rows = conn.execute(
                text("SELECT * FROM critical_operations ORDER BY id DESC LIMIT :limit"),
                {"limit": safe_limit},
            ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["intent"] = _json_load(data.pop("intent_json", None))
        data["result"] = _json_load(data.pop("result_json", None))
        out.append(data)
    return out


def critical_operations_summary(*, limit: int = 20) -> dict[str, Any]:
    rows = list_critical_operations(limit=limit)
    return {
        "total_recent": len(rows),
        "intent": sum(1 for r in rows if r.get("status") == "intent"),
        "success": sum(1 for r in rows if r.get("status") == "success"),
        "error": sum(1 for r in rows if r.get("status") == "error"),
        "blocked": sum(1 for r in rows if r.get("status") == "blocked"),
        "rows": rows,
    }


def format_critical_operations(rows: list[dict[str, Any]] | None = None, *, limit: int = 10) -> str:
    rows = rows if rows is not None else list_critical_operations(limit=limit)
    if not rows:
        return "Operações críticas\n\nNenhuma operação crítica registrada."
    lines = ["Operações críticas", "", f"Últimas {len(rows)} operações:"]
    for row in rows:
        lines.append(
            f"- {row.get('created_at')} — {row.get('category')}/{row.get('action')} "
            f"status={row.get('status')} chat={row.get('chat_id') or '-'} id={row.get('operation_id')}"
        )
    return "\n".join(lines)


def replay_packet(operation_id: str) -> str:
    row = get_critical_operation(operation_id)
    if not row:
        return "Pacote de replay seguro\n\nOperação não encontrada."
    return "\n".join(
        [
            "Pacote de replay seguro",
            "",
            f"operation_id: {row.get('operation_id')}",
            f"operation_key: {row.get('operation_key')}",
            f"category/action: {row.get('category')}/{row.get('action')}",
            f"status: {row.get('status')}",
            f"actor_user_id: {row.get('actor_user_id')}",
            f"chat_id: {row.get('chat_id')}",
            f"lock_name: {row.get('lock_name')}",
            f"intent_hash: {row.get('intent_hash')}",
            "",
            "Intenção:",
            json.dumps(row.get("intent") or {}, ensure_ascii=False, sort_keys=True, indent=2, default=str),
            "",
            "Resultado:",
            json.dumps(row.get("result") or {}, ensure_ascii=False, sort_keys=True, indent=2, default=str),
            "",
            "Replay automático não executado. Reaplique manualmente somente após validar intenção, lock e estado atual do grupo.",
        ]
    )



def export_critical_operations_jsonl(*, limit: int = 1000, status: str | None = None) -> bytes:
    """Exporta operações críticas em JSONL UTF-8 para investigação Owner-only."""
    rows = list_critical_operations(limit=max(1, min(int(limit), 5000)), status=status)
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def cleanup_critical_operations_older_than(days: int, *, keep_pending: bool = True) -> int:
    """Remove operações críticas antigas.

    Por padrão preserva operações em status `intent`, porque podem representar
    tentativa incompleta que ainda precisa de investigação.
    """
    ensure_tables()
    safe_days = max(1, int(days))
    cutoff = datetime.fromtimestamp(utcnow().timestamp() - safe_days * 86400, tz=timezone.utc).isoformat()
    with engine.begin() as conn:
        if keep_pending:
            res = conn.execute(
                text("DELETE FROM critical_operations WHERE created_at < :cutoff AND status != 'intent'"),
                {"cutoff": cutoff},
            )
        else:
            res = conn.execute(
                text("DELETE FROM critical_operations WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
    return int(res.rowcount or 0)
