from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text

from app.db.database import SessionLocal, engine
from app.utils.datetime import utcnow_naive

logger = logging.getLogger(__name__)

LEGACY_CUTOFF = datetime(2026, 6, 15, 0, 0, 0)
SILENT_MODE_KEY = "silent_mode_enabled"
LEGACY_MODE_KEY = "legacy_mode_enabled"
MAX_TELEGRAM_DOCUMENT_BYTES = 15 * 1024 * 1024
_ALLOWED_DURING_SILENT = {"start", "help"}
_ALLOWED_FOR_LEGACY_RELOGIN = {"start", "help", "login", "lastfm"}
_LOGIN_TABLES = ("lastfm_profiles", "spotify_tokens")
_INTERACTION_TABLES = (
    "bot_seen_updates",
    "tnow_recent_tracks",
    "track_plays",
    "track_reactions",
    "track_likes",
    "card_messages",
    "tnow_private_visibility",
)
_KNOWN_EXPORT_TABLES = (*_LOGIN_TABLES, "legacy_restricted_users", *_INTERACTION_TABLES)
_USER_ID_COLUMNS = ("user_id", "telegram_user_id", "owner_user_id", "created_by_owner_id", "released_by_user_id")
_IDENTIFIER_HINT_COLUMNS = (
    "id",
    "key",
    "cache_key",
    "track_id",
    "spotify_track_id",
    "canvas_fingerprint",
    "file_id",
    "file_unique_id",
    "chat_id",
    "message_id",
    "channel_chat_id",
    "channel_message_id",
    "user_id",
    "telegram_user_id",
    "owner_user_id",
    "created_by_owner_id",
    "released_by_user_id",
)
_DATE_HINT_COLUMNS = (
    "created_at",
    "updated_at",
    "played_at",
    "observed_at",
    "fetched_at",
    "expires_at",
    "expiration",
    "legacy_since",
    "released_at",
    "archived_at",
)
_TABLE_LABELS = {
    "lastfm_profiles": "inscricao Last fm",
    "spotify_tokens": "inscricao Spotify",
    "legacy_restricted_users": "estado legacy",
    "bot_seen_updates": "updates brutos recebidos pelo webhook",
    "tnow_recent_tracks": "cache recente /tnow",
    "track_plays": "plays/previews registrados",
    "track_reactions": "reacoes em cards",
    "track_likes": "likes legados",
    "card_messages": "cards enviados",
    "tnow_private_visibility": "regra owner /tpv",
}


@dataclass(frozen=True)
class ExportBundle:
    txt_bytes: bytes
    pdf_bytes: bytes
    txt_filename: str
    pdf_filename: str
    row_count: int
    login_row_count: int = 0
    interaction_row_count: int = 0
    user_count: int = 0


@dataclass(frozen=True)
class ListeningExportStats:
    row_count: int = 0
    login_row_count: int = 0
    interaction_row_count: int = 0
    user_count: int = 0
    present_tables: tuple[str, ...] = field(default_factory=tuple)
    known_missing_tables: tuple[str, ...] = field(default_factory=tuple)
    schema_count: int = 0


def ensure_operational_tables(conn, dialect_name: str) -> None:
    dt = "TIMESTAMP" if dialect_name == "postgresql" else "DATETIME"
    bigint = "BIGINT" if dialect_name == "postgresql" else "INTEGER"
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS operational_state (
                key VARCHAR PRIMARY KEY,
                value TEXT NOT NULL,
                updated_by_user_id {bigint},
                updated_at {dt} NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS legacy_restricted_users (
                user_id {bigint} PRIMARY KEY,
                reason TEXT NOT NULL,
                sources TEXT,
                legacy_since {dt},
                released_at {dt},
                released_by_user_id {bigint},
                created_at {dt} NOT NULL,
                updated_at {dt} NOT NULL
            )
            """
        )
    )
    try:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_legacy_restricted_users_released_at ON legacy_restricted_users(released_at)"))
    except Exception:
        logger.debug("legacy_restricted_users index skipped", exc_info=True)


def _value_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bool_to_value(value: bool) -> str:
    return "1" if value else "0"


def get_state_bool(key: str, default: bool = False) -> bool:
    try:
        with SessionLocal() as db:
            row = db.execute(text("SELECT value FROM operational_state WHERE key=:key"), {"key": key}).mappings().first()
            return _value_to_bool(str(row["value"]) if row else None, default=default)
    except Exception:
        logger.debug("OP_STATE_READ_FAILED key=%s", key, exc_info=True)
        return default


def set_state_bool(key: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
    now = utcnow_naive()
    value = _bool_to_value(enabled)
    dialect = engine.dialect.name
    sql = (
        """
        INSERT INTO operational_state (key, value, updated_by_user_id, updated_at)
        VALUES (:key, :value, :owner_user_id, :updated_at)
        ON CONFLICT (key) DO UPDATE SET
            value=excluded.value,
            updated_by_user_id=excluded.updated_by_user_id,
            updated_at=excluded.updated_at
        """
        if dialect == "postgresql"
        else """
        INSERT INTO operational_state (key, value, updated_by_user_id, updated_at)
        VALUES (:key, :value, :owner_user_id, :updated_at)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_by_user_id=excluded.updated_by_user_id,
            updated_at=excluded.updated_at
        """
    )
    with SessionLocal() as db:
        db.execute(text(sql), {"key": key, "value": value, "owner_user_id": owner_user_id, "updated_at": now})
        db.commit()


def silent_mode_enabled() -> bool:
    return get_state_bool(SILENT_MODE_KEY, default=False)


def legacy_mode_enabled() -> bool:
    return get_state_bool(LEGACY_MODE_KEY, default=False)


def set_silent_mode(enabled: bool, *, owner_user_id: int | None = None) -> None:
    set_state_bool(SILENT_MODE_KEY, enabled, owner_user_id=owner_user_id)


def set_legacy_mode(enabled: bool, *, owner_user_id: int | None = None) -> None:
    set_state_bool(LEGACY_MODE_KEY, enabled, owner_user_id=owner_user_id)


def _active_clause() -> str:
    return "released_at IS NULL"


def is_legacy_restricted(user_id: int) -> bool:
    if not legacy_mode_enabled():
        return False
    try:
        with SessionLocal() as db:
            row = db.execute(
                text(f"SELECT 1 FROM legacy_restricted_users WHERE user_id=:user_id AND {_active_clause()} LIMIT 1"),
                {"user_id": int(user_id)},
            ).first()
            return row is not None
    except Exception:
        logger.debug("LEGACY_RESTRICT_CHECK_FAILED user=%s", user_id, exc_info=True)
        return False


def release_legacy_restriction(user_id: int, *, by_user_id: int | None = None) -> bool:
    now = utcnow_naive()
    with SessionLocal() as db:
        result = db.execute(
            text(
                """
                UPDATE legacy_restricted_users
                SET released_at=:released_at,
                    released_by_user_id=:released_by_user_id,
                    updated_at=:updated_at
                WHERE user_id=:user_id AND released_at IS NULL
                """
            ),
            {
                "released_at": now,
                "released_by_user_id": by_user_id,
                "updated_at": now,
                "user_id": int(user_id),
            },
        )
        db.commit()
        return bool(getattr(result, "rowcount", 0) or 0)


def release_legacy_after_login(user_id: int, *, source: str | None = None) -> None:
    released = release_legacy_restriction(user_id, by_user_id=None)
    if released:
        logger.info("LEGACY_RESTRICTION_RELEASED_AFTER_LOGIN user_id=%s source=%s", user_id, source or "unknown")


def _insert_legacy_sql(dialect: str) -> str:
    if dialect == "postgresql":
        return """
            INSERT INTO legacy_restricted_users
                (user_id, reason, sources, legacy_since, released_at, released_by_user_id, created_at, updated_at)
            VALUES
                (:user_id, :reason, :sources, :legacy_since, NULL, NULL, :created_at, :updated_at)
            ON CONFLICT (user_id) DO NOTHING
        """
    return """
        INSERT OR IGNORE INTO legacy_restricted_users
            (user_id, reason, sources, legacy_since, released_at, released_by_user_id, created_at, updated_at)
        VALUES
            (:user_id, :reason, :sources, :legacy_since, NULL, NULL, :created_at, :updated_at)
    """


def refresh_legacy_restrictions(*, cutoff: datetime = LEGACY_CUTOFF) -> int:
    """Populate the legacy restriction table from persisted login records.

    A user is considered legacy only when the login row was created before the
    cutoff and has not been updated/reconfirmed after the cutoff. This lets a
    user leave the restriction by logging in again.
    """
    dialect = engine.dialect.name
    now = utcnow_naive()
    inserted = 0
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    candidates: dict[int, dict[str, Any]] = {}

    with SessionLocal() as db:
        if "lastfm_profiles" in tables:
            rows = db.execute(
                text(
                    """
                    SELECT user_id, username, created_at, updated_at
                    FROM lastfm_profiles
                    WHERE created_at < :cutoff
                      AND (updated_at IS NULL OR updated_at < :cutoff)
                    """
                ),
                {"cutoff": cutoff},
            ).mappings().all()
            for row in rows:
                uid = int(row["user_id"])
                item = candidates.setdefault(uid, {"sources": [], "legacy_since": row.get("created_at")})
                item["sources"].append({
                    "table": "lastfm_profiles",
                    "username": row.get("username"),
                    "created_at": str(row.get("created_at")),
                    "updated_at": str(row.get("updated_at")),
                })

        if "spotify_tokens" in tables:
            columns = {column["name"] for column in inspector.get_columns("spotify_tokens")}
            if "created_at" in columns:
                updated_expr = "updated_at" if "updated_at" in columns else "created_at"
                rows = db.execute(
                    text(
                        f"""
                        SELECT user_id, created_at, {updated_expr} AS updated_at, expiration
                        FROM spotify_tokens
                        WHERE created_at < :cutoff
                          AND ({updated_expr} IS NULL OR {updated_expr} < :cutoff)
                        """
                    ),
                    {"cutoff": cutoff},
                ).mappings().all()
                for row in rows:
                    uid = int(row["user_id"])
                    item = candidates.setdefault(uid, {"sources": [], "legacy_since": row.get("created_at")})
                    item["sources"].append({
                        "table": "spotify_tokens",
                        "created_at": str(row.get("created_at")),
                        "updated_at": str(row.get("updated_at")),
                        "expiration": str(row.get("expiration")),
                    })

        insert_sql = _insert_legacy_sql(dialect)
        for uid, item in candidates.items():
            result = db.execute(
                text(insert_sql),
                {
                    "user_id": uid,
                    "reason": f"login anterior a {cutoff.date().isoformat()} sem reconfirmacao posterior",
                    "sources": json.dumps(item.get("sources") or [], ensure_ascii=False, default=str),
                    "legacy_since": item.get("legacy_since") or now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            inserted += int(getattr(result, "rowcount", 0) or 0)
        db.commit()
    logger.info("LEGACY_RESTRICTIONS_REFRESHED candidates=%s inserted=%s cutoff=%s", len(candidates), inserted, cutoff.isoformat())
    return inserted


def legacy_counts() -> dict[str, int]:
    try:
        with SessionLocal() as db:
            active = db.execute(text("SELECT COUNT(*) FROM legacy_restricted_users WHERE released_at IS NULL")).scalar() or 0
            released = db.execute(text("SELECT COUNT(*) FROM legacy_restricted_users WHERE released_at IS NOT NULL")).scalar() or 0
            return {"active": int(active), "released": int(released), "total": int(active) + int(released)}
    except Exception:
        logger.debug("LEGACY_COUNTS_FAILED", exc_info=True)
        return {"active": 0, "released": 0, "total": 0}


def _command_name_from_text(value: str | None) -> str | None:
    if not value:
        return None
    first = value.strip().split(maxsplit=1)[0]
    if not first.startswith("/"):
        return None
    command = first[1:].split("@", 1)[0].strip().lower()
    return command or None


def _message_command(update: Any) -> str | None:
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    return _command_name_from_text(getattr(message, "text", None)) if message is not None else None


def _update_user_id(update: Any) -> int | None:
    for attr in ("message", "edited_message", "inline_query", "chosen_inline_result"):
        obj = getattr(update, attr, None)
        user = getattr(obj, "from_user", None)
        if user is not None and getattr(user, "id", None) is not None:
            return int(user.id)
    callback = getattr(update, "callback_query", None)
    if callback is not None and getattr(callback, "from_user", None) is not None:
        return int(callback.from_user.id)
    reaction = getattr(update, "message_reaction", None)
    if reaction is not None and getattr(reaction, "user", None) is not None:
        return int(reaction.user.id)
    return None


def user_id_from_update(update: Any) -> int | None:
    return _update_user_id(update)


def should_drop_update_for_operational_controls(update: Any, *, is_owner: bool) -> bool:
    if is_owner:
        return False
    user_id = _update_user_id(update)
    command = _message_command(update)

    if silent_mode_enabled():
        return command not in _ALLOWED_DURING_SILENT

    if user_id is not None and is_legacy_restricted(user_id):
        return command not in _ALLOWED_FOR_LEGACY_RELOGIN

    return False


def _stringify(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _quote_identifier(name: str) -> str:
    """Quote a known database identifier after a strict allowlist check."""
    if not name or not all(char.isalnum() or char == "_" for char in name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def _payload_event_type(payload: dict[str, Any]) -> str:
    for key in (
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "message_reaction",
        "message_reaction_count",
        "channel_post",
        "edited_channel_post",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "poll",
        "poll_answer",
    ):
        if isinstance(payload.get(key), dict) or payload.get(key) is not None:
            return key
    for key in payload:
        if key != "update_id":
            return str(key)
    return "unknown"


def _payload_user(payload: dict[str, Any], event_type: str) -> dict[str, Any] | None:
    event = payload.get(event_type)
    if not isinstance(event, dict):
        return None
    if event_type in {"message", "edited_message", "channel_post", "edited_channel_post"}:
        user = event.get("from")
        return user if isinstance(user, dict) else None
    if event_type in {"callback_query", "inline_query", "chosen_inline_result", "poll_answer"}:
        user = event.get("from")
        return user if isinstance(user, dict) else None
    if event_type == "message_reaction":
        user = event.get("user") or event.get("actor_chat")
        return user if isinstance(user, dict) else None
    if event_type in {"my_chat_member", "chat_member", "chat_join_request"}:
        user = event.get("from") or event.get("user")
        return user if isinstance(user, dict) else None
    return None


def _payload_chat(payload: dict[str, Any], event_type: str) -> dict[str, Any] | None:
    event = payload.get(event_type)
    if not isinstance(event, dict):
        return None
    if event_type == "callback_query":
        message = event.get("message")
        if isinstance(message, dict) and isinstance(message.get("chat"), dict):
            return message.get("chat")
    chat = event.get("chat")
    return chat if isinstance(chat, dict) else None


def _payload_message(payload: dict[str, Any], event_type: str) -> dict[str, Any] | None:
    event = payload.get(event_type)
    if not isinstance(event, dict):
        return None
    if event_type == "callback_query":
        message = event.get("message")
        return message if isinstance(message, dict) else None
    if event_type in {"message", "edited_message", "channel_post", "edited_channel_post"}:
        return event
    return None


def _payload_command(text_value: str | None) -> str | None:
    return _command_name_from_text(text_value)


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def record_seen_update_payload(payload: dict[str, Any], *, source: str = "webhook", dropped_by_ops: bool | None = None) -> None:
    """Persist the raw Telegram update exactly as the bot received it.

    /listening can only export what exists in storage. This table closes the
    audit gap for new interactions by keeping the original webhook payload plus
    searchable identifiers. Failure here must never break the bot flow.
    """
    try:
        if not isinstance(payload, dict):
            return
        event_type = _payload_event_type(payload)
        event = payload.get(event_type) if isinstance(payload.get(event_type), dict) else {}
        user = _payload_user(payload, event_type) or {}
        chat = _payload_chat(payload, event_type) or {}
        message = _payload_message(payload, event_type) or {}
        text_value = message.get("text") if isinstance(message, dict) else None
        callback_data = None
        inline_query = None
        if event_type == "callback_query" and isinstance(event, dict):
            callback_data = event.get("data")
        if event_type == "inline_query" and isinstance(event, dict):
            inline_query = event.get("query")
        now = utcnow_naive()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO bot_seen_updates (
                        update_id, event_type, telegram_user_id, chat_id, message_id,
                        command, text, callback_data, inline_query, source,
                        dropped_by_ops, payload_json, created_at
                    ) VALUES (
                        :update_id, :event_type, :telegram_user_id, :chat_id, :message_id,
                        :command, :text, :callback_data, :inline_query, :source,
                        :dropped_by_ops, :payload_json, :created_at
                    )
                    """
                ),
                {
                    "update_id": _try_int(payload.get("update_id")),
                    "event_type": event_type,
                    "telegram_user_id": _try_int(user.get("id")),
                    "chat_id": _try_int(chat.get("id")),
                    "message_id": _try_int(message.get("message_id") or (event.get("message_id") if isinstance(event, dict) else None)),
                    "command": _payload_command(str(text_value) if text_value is not None else None),
                    "text": str(text_value) if text_value is not None else None,
                    "callback_data": str(callback_data) if callback_data is not None else None,
                    "inline_query": str(inline_query) if inline_query is not None else None,
                    "source": source,
                    "dropped_by_ops": dropped_by_ops,
                    "payload_json": _safe_json_dumps(payload),
                    "created_at": now,
                },
            )
    except Exception:
        logger.debug("BOT_SEEN_UPDATE_RECORD_FAILED", exc_info=True)


def _collect_distinct_integer_values(column_candidates: tuple[str, ...]) -> list[int]:
    values: set[int] = set()
    inspector = inspect(engine)
    for table_name in _export_table_names(inspector):
        try:
            schema = _table_schema(table_name, inspector)
            columns = [str(column.get("name") or "") for column in schema.get("columns") or []]
            matching = [column for column in columns if column in column_candidates]
            for column in columns:
                lowered = column.lower()
                if lowered.endswith("_user_id") and "user_id" in column_candidates:
                    matching.append(column)
                if lowered.endswith("chat_id") and "chat_id" in column_candidates:
                    matching.append(column)
            for column in sorted(set(matching)):
                with SessionLocal() as db:
                    rows = db.execute(
                        text(
                            f"SELECT DISTINCT {_quote_identifier(column)} AS value FROM {_quote_identifier(table_name)} "
                            f"WHERE {_quote_identifier(column)} IS NOT NULL"
                        )
                    ).mappings().all()
                for row in rows:
                    parsed = _try_int(row.get("value"))
                    if parsed is not None:
                        values.add(parsed)
        except Exception:
            logger.debug("LISTENING_DISTINCT_VALUE_COLLECT_SKIPPED table=%s", table_name, exc_info=True)
    return sorted(values)


def listening_known_user_ids() -> list[int]:
    return _collect_distinct_integer_values(("user_id", "telegram_user_id", "owner_user_id", "created_by_owner_id", "released_by_user_id"))


def listening_known_chat_ids() -> list[int]:
    return _collect_distinct_integer_values(("chat_id", "channel_chat_id"))


def _safe_inspector_call(default: Any, func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception:
        logger.debug("LISTENING_SCHEMA_INTROSPECTION_SKIPPED func=%s args=%s", getattr(func, "__name__", repr(func)), args, exc_info=True)
        return default


def _export_table_names(inspector: Any) -> list[str]:
    """Return every table visible in the configured database schema.

    /listening is an owner administrative export. It must not depend on a
    selective allowlist, because old deployments may contain legacy tables or
    emergency/debug tables that are not mapped by the current SQLAlchemy models.
    Known music-login/interaction tables are ordered first for readability;
    every remaining table is exported after them.
    """
    tables = list(_safe_inspector_call([], inspector.get_table_names))
    known = [table for table in _KNOWN_EXPORT_TABLES if table in tables]
    rest = sorted(table for table in tables if table not in set(known))
    return [*known, *rest]


def _table_schema(table_name: str, inspector: Any | None = None) -> dict[str, Any]:
    inspector = inspector or inspect(engine)
    columns = _safe_inspector_call([], inspector.get_columns, table_name)
    pk = _safe_inspector_call({}, inspector.get_pk_constraint, table_name) or {}
    indexes = _safe_inspector_call([], inspector.get_indexes, table_name)
    uniques = _safe_inspector_call([], inspector.get_unique_constraints, table_name)
    fks = _safe_inspector_call([], inspector.get_foreign_keys, table_name)
    return {
        "columns": [
            {
                "name": str(column.get("name") or ""),
                "type": str(column.get("type") or ""),
                "nullable": bool(column.get("nullable", True)),
                "primary_key": bool(column.get("primary_key", False)),
                "default": _stringify(column.get("default")),
            }
            for column in columns
            if column.get("name")
        ],
        "primary_key": list(pk.get("constrained_columns") or []),
        "indexes": indexes,
        "unique_constraints": uniques,
        "foreign_keys": fks,
    }


def _order_columns_for_table(schema: dict[str, Any]) -> list[str]:
    column_names = [str(column.get("name") or "") for column in schema.get("columns") or [] if column.get("name")]
    pk_columns = [str(column) for column in schema.get("primary_key") or [] if column in column_names]
    if pk_columns:
        return pk_columns
    for preferred in ("user_id", "telegram_user_id", "owner_user_id", "created_at", "updated_at", "id", "key", "cache_key"):
        if preferred in column_names:
            return [preferred]
    return column_names[:1]


def _table_rows(table_name: str, inspector: Any | None = None) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
    inspector = inspector or inspect(engine)
    tables = set(_safe_inspector_call([], inspector.get_table_names))
    if table_name not in tables:
        return [], {"columns": [], "primary_key": [], "indexes": [], "unique_constraints": [], "foreign_keys": []}, []
    schema = _table_schema(table_name, inspector)
    columns = [column["name"] for column in schema.get("columns") or []]
    if not columns:
        return [], schema, []
    table_sql = _quote_identifier(table_name)
    order_columns = _order_columns_for_table(schema)
    order_clause = ""
    if order_columns:
        order_clause = " ORDER BY " + ", ".join(_quote_identifier(column) for column in order_columns)
    with SessionLocal() as db:
        rows = db.execute(text(f"SELECT * FROM {table_sql}{order_clause}")).mappings().all()
        return columns, schema, [dict(row) for row in rows]


def _identifier_values(row: dict[str, Any], columns: list[str]) -> list[str]:
    values: list[str] = []
    for column in columns:
        lowered = column.lower()
        if column in _IDENTIFIER_HINT_COLUMNS or lowered.endswith("_id") or lowered.endswith("_key") or lowered.endswith("_hash"):
            raw = row.get(column)
            if raw is not None and raw != "":
                values.append(f"{column}={_stringify(raw)}")
    return values


def _try_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_datetime(value: datetime) -> datetime:
    """Return UTC naive datetime for safe comparisons across exported DB values.

    Existing project timestamps are stored mostly as naive UTC values, but
    some values can be timezone-aware ISO strings, for example values ending
    with ``Z`` or ``+00:00``. Python cannot compare naive and aware datetimes,
    so the listening export normalizes every parsed date before min/max checks.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def _try_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return _normalize_datetime(datetime.fromisoformat(raw))
    except Exception:
        return None


def _date_values(row: dict[str, Any]) -> list[datetime]:
    values: list[datetime] = []
    for column in _DATE_HINT_COLUMNS:
        if column not in row:
            continue
        parsed = _try_datetime(row.get(column))
        if parsed is not None:
            values.append(parsed)
    return values


def _compact_track(row: dict[str, Any]) -> str:
    title = row.get("track_name") or row.get("title") or row.get("track_id") or ""
    artist = row.get("artist") or row.get("artist_name") or ""
    if title and artist:
        return f"{title} - {artist}"
    return _stringify(title or artist or row.get("track_id") or "")


def _increment_counter(counter: dict[str, int], key: Any) -> None:
    label = _stringify(key).strip() or "-"
    counter[label] = int(counter.get(label, 0)) + 1


def _counter_text(counter: dict[str, int], *, limit: int = 20) -> str:
    if not counter:
        return "-"
    items = sorted(counter.items(), key=lambda item: (-int(item[1]), str(item[0])))[:limit]
    return ", ".join(f"{key}={value}" for key, value in items)


def _display_name_from_user_dict(user: dict[str, Any]) -> str:
    title = _stringify(user.get("title")).strip()
    if title:
        return title
    parts = [
        _stringify(user.get("first_name")).strip(),
        _stringify(user.get("last_name")).strip(),
    ]
    name = " ".join(part for part in parts if part).strip()
    return name or _stringify(user.get("full_name")).strip() or _stringify(user.get("id")).strip()


def _username_from_user_dict(user: dict[str, Any]) -> str:
    value = _stringify(user.get("username")).strip()
    return f"@{value}" if value and not value.startswith("@") else value


def _telegram_identity_summary(user: dict[str, Any]) -> str:
    if not user:
        return "-"
    parts = []
    display = _display_name_from_user_dict(user)
    if display:
        parts.append(f"nome={display}")
    username = _username_from_user_dict(user)
    if username:
        parts.append(f"username={username}")
    for key in ("id", "type", "is_bot", "language_code", "source", "source_table"):
        if user.get(key) not in (None, ""):
            parts.append(f"{key}={_stringify(user.get(key))}")
    return "; ".join(parts) if parts else _stringify(user)


def _identity_key(user: dict[str, Any]) -> str:
    relevant = {
        key: user.get(key)
        for key in ("id", "first_name", "last_name", "username", "title", "type", "is_bot", "language_code")
        if user.get(key) not in (None, "")
    }
    return json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)


def _row_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("payload_json")
    if raw in (None, ""):
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _chat_type_from_payload(payload: dict[str, Any], event_type: str) -> str | None:
    chat = _payload_chat(payload, event_type)
    if isinstance(chat, dict):
        return _stringify(chat.get("type")).strip() or None
    return None


def _event_label_from_update_row(row: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    event_type = _stringify(row.get("event_type")).strip() or ( _payload_event_type(payload) if payload else "unknown" )
    chat_id = _stringify(row.get("chat_id")).strip()
    message_id = _stringify(row.get("message_id")).strip()
    command = _stringify(row.get("command")).strip()
    source = _stringify(row.get("source")).strip()
    chat_type = _chat_type_from_payload(payload, event_type) if payload else None
    parts = [f"evento={event_type}"]
    if chat_type:
        parts.append(f"modo_chat={chat_type}")
    if command:
        parts.append(f"comando=/{command}")
    if source:
        parts.append(f"origem={source}")
    if chat_id:
        parts.append(f"chat_id={chat_id}")
    if message_id:
        parts.append(f"message_id={message_id}")
    return "; ".join(parts)


def _event_sort_key(event: dict[str, Any]) -> datetime:
    parsed = _try_datetime(event.get("at"))
    return parsed or datetime.min


def _api_user_identity_map(api_debug: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    if not isinstance(api_debug, dict):
        return result
    for item in api_debug.get("user_chats") or []:
        if not isinstance(item, dict):
            continue
        user_id = _try_int(item.get("user_id"))
        if user_id is None:
            continue
        chat = item.get("get_chat")
        if isinstance(chat, dict):
            result[user_id] = chat
        elif item.get("get_chat_error"):
            result[user_id] = {"api_error": item.get("get_chat_error")}
    return result


def _api_debug_overview(api_debug: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    lines.append("[estatistica final enriquecida por API]")
    if not isinstance(api_debug, dict):
        lines.append("  API nao consultada nesta exportacao.")
        lines.append("")
        return lines
    user_items = [item for item in (api_debug.get("user_chats") or []) if isinstance(item, dict)]
    chat_items = [item for item in (api_debug.get("chat_debug") or []) if isinstance(item, dict)]
    users_ok = sum(1 for item in user_items if isinstance(item.get("get_chat"), dict))
    users_err = sum(1 for item in user_items if item.get("get_chat_error"))
    chats_ok = sum(1 for item in chat_items if isinstance(item.get("get_chat"), dict))
    chats_err = sum(1 for item in chat_items if item.get("get_chat_error"))
    resolved_usernames = []
    for item in user_items:
        chat = item.get("get_chat")
        if isinstance(chat, dict) and chat.get("username"):
            resolved_usernames.append(f"{item.get('user_id')}=@{chat.get('username')}")
    lines.append(f"  usuarios conhecidos no banco: {_stringify(api_debug.get('known_user_ids_total'))}")
    lines.append(f"  chats conhecidos no banco: {_stringify(api_debug.get('known_chat_ids_total'))}")
    lines.append(f"  usuarios consultados via getChat: {_stringify(api_debug.get('users_queried'))}; ok={users_ok}; erro={users_err}; nao consultados={_stringify(api_debug.get('users_not_queried_due_to_limit'))}")
    lines.append(f"  chats consultados via getChat/getChatMember: {_stringify(api_debug.get('chats_queried'))}; ok={chats_ok}; erro={chats_err}; nao consultados={_stringify(api_debug.get('chats_not_queried_due_to_limit'))}")
    if resolved_usernames:
        lines.append(f"  usernames publicos resolvidos: {', '.join(resolved_usernames[:50])}" + (" ..." if len(resolved_usernames) > 50 else ""))
    errors = api_debug.get("errors") or []
    if errors:
        lines.append(f"  erros gerais de API: {_stringify(errors)}")
    lines.append("")
    return lines


def _row_user_roles(row: dict[str, Any], columns: list[str]) -> list[tuple[str, int]]:
    roles: list[tuple[str, int]] = []
    for column in _USER_ID_COLUMNS:
        if column not in columns:
            continue
        user_id = _try_int(row.get(column))
        if user_id is not None:
            roles.append((column, user_id))
    return roles


def _json_dict_from_value(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _row_identity_candidates(table_name: str, role: str, row: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
    """Extract Telegram identity from any table row that stores it.

    Older TR4 tables already contain usable public identity fields, but the
    first /listening enriched report only consumed identities from
    bot_seen_updates and live getChat. This helper mines all persisted rows so
    the summary uses what the bot already saved before raw-update auditing was
    added.
    """
    identities: list[dict[str, Any]] = []

    for json_column in ("user_json", "actor_json", "from_user_json", "payload_json", "payload_tecnico_json", "context_json"):
        parsed = _json_dict_from_value(row.get(json_column))
        if not parsed:
            continue
        # Direct Telegram WebApp/auth user payload.
        if _try_int(parsed.get("id")) == user_id:
            item = dict(parsed)
            item.setdefault("source", json_column)
            item.setdefault("source_table", table_name)
            identities.append(item)
        # Nested Telegram user payloads inside generic JSON.
        for nested_key in ("from", "user", "actor", "telegram_user"):
            nested = parsed.get(nested_key)
            if isinstance(nested, dict) and _try_int(nested.get("id")) == user_id:
                item = dict(nested)
                item.setdefault("source", f"{json_column}.{nested_key}")
                item.setdefault("source_table", table_name)
                identities.append(item)

    # Explicit profile table.
    if table_name == "telegram_user_profiles":
        item = {
            "id": user_id,
            "first_name": row.get("first_name"),
            "last_name": row.get("last_name"),
            "username": row.get("username"),
            "full_name": row.get("full_name"),
            "language_code": row.get("language_code"),
            "source": row.get("source") or "telegram_user_profiles",
            "source_table": table_name,
        }
        identities.append(item)

    # Generic public identity columns used by moderation/private-session tables.
    name = (
        row.get("user_name")
        or row.get("nome_publico")
        or row.get("nome")
        or row.get("actor_name")
        or row.get("actor_label")
        or row.get("full_name")
        or row.get("title")
    )
    username = row.get("user_username") or row.get("username") or row.get("actor_username")
    if name or username:
        item = {
            "id": user_id,
            "first_name": name,
            "username": username,
            "source": role,
            "source_table": table_name,
        }
        identities.append(item)

    # Chat tables can identify chats/groups. Keep them separately but in the
    # same identity structure when the role value being summarized is a chat id.
    if "chat" in role:
        chat_title = row.get("title") or row.get("titulo") or row.get("ui_label") or row.get("nome_publico")
        chat_username = row.get("username")
        if chat_title or chat_username:
            identities.append(
                {
                    "id": user_id,
                    "title": chat_title,
                    "username": chat_username,
                    "type": "chat_or_group_saved",
                    "source": role,
                    "source_table": table_name,
                }
            )

    unique: dict[str, dict[str, Any]] = {}
    for item in identities:
        cleaned = {key: value for key, value in item.items() if value not in (None, "")}
        if not cleaned:
            continue
        unique[_identity_key(cleaned)] = cleaned
    return list(unique.values())

def _add_user_fact(users: dict[int, dict[str, Any]], user_id: int, *, table_name: str, role: str, row: dict[str, Any]) -> None:
    user = users.setdefault(
        user_id,
        {
            "tables": set(),
            "roles": set(),
            "first_seen": None,
            "last_seen": None,
            "lastfm_usernames": set(),
            "spotify_connected": False,
            "spotify_expirations": [],
            "legacy_status": "nao listado",
            "tpv_rules": [],
            "activity": {},
            "latest_tracks": [],
            "telegram_saved_identities": {},
            "event_types": {},
            "chat_types": {},
            "commands": {},
            "sources": {},
            "dropped_by_ops": {},
            "first_event": None,
            "last_event": None,
            "recent_events": [],
            "lastfm_rows": [],
            "spotify_token_rows": [],
        },
    )
    user["tables"].add(table_name)
    user["roles"].add(f"{table_name}.{role}")
    for identity in _row_identity_candidates(table_name, role, row, user_id):
        user["telegram_saved_identities"][_identity_key(identity)] = identity
    for parsed in _date_values(row):
        first = user.get("first_seen")
        last = user.get("last_seen")
        if first is None or parsed < first:
            user["first_seen"] = parsed
        if last is None or parsed > last:
            user["last_seen"] = parsed

    activity = user["activity"]
    activity[table_name] = int(activity.get(table_name, 0)) + 1

    if table_name == "lastfm_profiles":
        username = row.get("username")
        if username:
            user["lastfm_usernames"].add(str(username))
        user["lastfm_rows"].append({key: _stringify(value) for key, value in row.items()})
    elif table_name == "spotify_tokens":
        user["spotify_connected"] = True
        if row.get("expiration"):
            user["spotify_expirations"].append(_stringify(row.get("expiration")))
        # Owner-only export: keep every token field exactly as stored.
        user["spotify_token_rows"].append({key: _stringify(value) for key, value in row.items()})
    elif table_name == "legacy_restricted_users":
        user["legacy_status"] = "liberado" if row.get("released_at") else "ativo"
    elif table_name == "tnow_private_visibility":
        user["tpv_rules"].append(
            f"mode={_stringify(row.get('mode')) or '-'}; label={_stringify(row.get('display_label')) or '-'}; enabled={_stringify(row.get('enabled')) or '-'}"
        )
    elif table_name == "bot_seen_updates":
        payload = _row_payload(row)
        event_type = _stringify(row.get("event_type")).strip() or (_payload_event_type(payload) if payload else "unknown")
        _increment_counter(user["event_types"], event_type)
        _increment_counter(user["sources"], row.get("source"))
        _increment_counter(user["dropped_by_ops"], row.get("dropped_by_ops"))
        command = _stringify(row.get("command")).strip()
        if command:
            _increment_counter(user["commands"], f"/{command}")
        if payload:
            chat_type = _chat_type_from_payload(payload, event_type)
            if chat_type:
                _increment_counter(user["chat_types"], chat_type)
            identity = _payload_user(payload, event_type)
            if isinstance(identity, dict) and identity.get("id") is not None:
                user["telegram_saved_identities"][_identity_key(identity)] = identity
            # In private chats, Telegram chat fields can also contain username/name.
            chat = _payload_chat(payload, event_type)
            if isinstance(chat, dict) and _try_int(chat.get("id")) == user_id:
                user["telegram_saved_identities"][_identity_key(chat)] = chat
        event = {
            "at": _stringify(row.get("created_at")),
            "label": _event_label_from_update_row(row, payload),
            "text": _stringify(row.get("text")),
            "callback_data": _stringify(row.get("callback_data")),
            "inline_query": _stringify(row.get("inline_query")),
        }
        first_event = user.get("first_event")
        last_event = user.get("last_event")
        if first_event is None or _event_sort_key(event) < _event_sort_key(first_event):
            user["first_event"] = event
        if last_event is None or _event_sort_key(event) > _event_sort_key(last_event):
            user["last_event"] = event
        user["recent_events"].append(event)
    elif table_name in {"tnow_recent_tracks", "track_plays", "track_likes", "track_reactions"}:
        track = _compact_track(row)
        if track:
            when = row.get("played_at") or row.get("observed_at") or row.get("created_at") or row.get("updated_at")
            user["latest_tracks"].append((_stringify(when), table_name, track))


def _collect_listening_tables() -> tuple[dict[str, dict[str, Any]], ListeningExportStats, dict[int, dict[str, Any]]]:
    data: dict[str, dict[str, Any]] = {}
    users: dict[int, dict[str, Any]] = {}
    total_rows = 0
    login_rows = 0
    interaction_rows = 0

    inspector = inspect(engine)
    export_tables = _export_table_names(inspector)
    present = list(export_tables)
    known_missing = [table for table in _KNOWN_EXPORT_TABLES if table not in set(export_tables)]

    for table_name in export_tables:
        columns, schema, rows = _table_rows(table_name, inspector)
        data[table_name] = {"columns": columns, "schema": schema, "rows": rows}
        total_rows += len(rows)
        if table_name in _LOGIN_TABLES:
            login_rows += len(rows)
        elif table_name in _INTERACTION_TABLES:
            interaction_rows += len(rows)
        for row in rows:
            roles = _row_user_roles(row, columns)
            for role, user_id in roles:
                _add_user_fact(users, user_id, table_name=table_name, role=role, row=row)

    stats = ListeningExportStats(
        row_count=total_rows,
        login_row_count=login_rows,
        interaction_row_count=interaction_rows,
        user_count=len(users),
        present_tables=tuple(present),
        known_missing_tables=tuple(known_missing),
        schema_count=len(export_tables),
    )
    return data, stats, users


def _format_user_summary_lines(users: dict[int, dict[str, Any]], *, api_debug: dict[str, Any] | None = None) -> list[str]:
    lines: list[str] = []
    lines.append("[resumo por usuario identificado - final enriquecido]")
    lines.append("  Este resumo cruza tudo que foi salvo no banco com o que a Telegram Bot API conseguiu resolver no momento do /listening.")
    lines.append("  Tokens e identificadores tambem aparecem no dump integral por tabela abaixo; aqui entram organizados por user_id.")
    if not users:
        lines.append("  nenhum usuario identificado nas tabelas exportadas")
        lines.append("")
        return lines

    api_map = _api_user_identity_map(api_debug)
    for user_id in sorted(users):
        user = users[user_id]
        api_identity = api_map.get(user_id) or {}
        saved_identities = list((user.get("telegram_saved_identities") or {}).values())
        preferred_saved = saved_identities[-1] if saved_identities else {}
        lines.append(f"  usuario_id: {user_id}")
        lines.append(f"    Telegram salvo no banco: {_telegram_identity_summary(preferred_saved)}")
        if len(saved_identities) > 1:
            lines.append(f"    Telegram salvo - historico de nomes/usernames/fontes: {' | '.join(_telegram_identity_summary(item) for item in saved_identities[-8:])}")
        lines.append(f"    Telegram API atual/getChat: {_telegram_identity_summary(api_identity if not api_identity.get('api_error') else {})}")
        if api_identity.get("api_error"):
            lines.append(f"    Telegram API erro: {_stringify(api_identity.get('api_error'))}")

        usernames = sorted(user["lastfm_usernames"])
        lines.append(f"    Last fm usernames salvos: {', '.join(usernames) if usernames else '-'}")
        if user.get("lastfm_rows"):
            lines.append("    inscricoes Last fm completas:")
            for row in user["lastfm_rows"]:
                lines.append(f"      - {_stringify(row)}")

        spotify_exp = sorted(set(user["spotify_expirations"]))
        spotify_text = "sim" if user["spotify_connected"] else "nao"
        if spotify_exp:
            spotify_text += f"; expiracoes={', '.join(spotify_exp[-3:])}"
        lines.append(f"    Spotify conectado: {spotify_text}")
        if user.get("spotify_token_rows"):
            lines.append("    tokens Spotify salvos completos:")
            for index, row in enumerate(user["spotify_token_rows"], start=1):
                lines.append(f"      token_row_{index}: {_stringify(row)}")

        first_event = user.get("first_event") or {}
        last_event = user.get("last_event") or {}
        first_seen = _stringify(user.get("first_seen")) or "-"
        last_seen = _stringify(user.get("last_seen")) or "-"
        lines.append(f"    primeira data vista no banco: {first_seen}")
        lines.append(f"    ultima data vista no banco: {last_seen}")
        if first_event:
            lines.append(f"    primeira entrada/interacao bruta salva: {_stringify(first_event.get('at')) or '-'} | {_stringify(first_event.get('label'))}")
            if first_event.get("text"):
                lines.append(f"      texto inicial: {_stringify(first_event.get('text'))}")
        else:
            lines.append("    primeira entrada/interacao bruta salva: -")
        if last_event:
            lines.append(f"    ultima interacao bruta salva: {_stringify(last_event.get('at')) or '-'} | {_stringify(last_event.get('label'))}")

        lines.append(f"    modo/eventos salvos: {_counter_text(user.get('event_types') or {})}")
        lines.append(f"    modo por tipo de chat: {_counter_text(user.get('chat_types') or {})}")
        lines.append(f"    comandos usados: {_counter_text(user.get('commands') or {})}")
        lines.append(f"    origem dos registros: {_counter_text(user.get('sources') or {})}")
        lines.append(f"    dropped_by_ops: {_counter_text(user.get('dropped_by_ops') or {})}")
        lines.append(f"    legacy: {user['legacy_status']}")

        roles = sorted(user["roles"])
        lines.append(f"    papeis/colunas onde aparece: {', '.join(roles) if roles else '-'}")
        tables = sorted(user["tables"])
        lines.append(f"    tabelas vinculadas: {', '.join(tables) if tables else '-'}")
        if user["tpv_rules"]:
            lines.append(f"    regras /tpv: {' | '.join(user['tpv_rules'])}")
        activity = user["activity"]
        if activity:
            parts = [f"{table}={activity[table]}" for table in sorted(activity)]
            lines.append(f"    contagem por tabela: {', '.join(parts)}")
        latest = sorted(user["latest_tracks"], key=lambda item: item[0], reverse=True)[:8]
        if latest:
            lines.append("    musicas/interacoes recentes inferidas:")
            for when, table_name, track in latest:
                lines.append(f"      - {when or '-'} | {table_name} | {track}")
        recent_events = sorted(user.get("recent_events") or [], key=_event_sort_key, reverse=True)[:8]
        if recent_events:
            lines.append("    ultimos updates brutos salvos:")
            for event in recent_events:
                extra = ""
                if event.get("callback_data"):
                    extra = f" | callback={_stringify(event.get('callback_data'))}"
                elif event.get("inline_query"):
                    extra = f" | inline_query={_stringify(event.get('inline_query'))}"
                elif event.get("text"):
                    extra = f" | text={_stringify(event.get('text'))}"
                lines.append(f"      - {_stringify(event.get('at')) or '-'} | {_stringify(event.get('label'))}{extra}")
        lines.append("")
    return lines


def _format_schema_lines(table_name: str, schema: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    columns = list(schema.get("columns") or [])
    pk = list(schema.get("primary_key") or [])
    indexes = list(schema.get("indexes") or [])
    uniques = list(schema.get("unique_constraints") or [])
    fks = list(schema.get("foreign_keys") or [])
    lines.append(f"  identificadores/primary key: {', '.join(pk) if pk else '-'}")
    if indexes:
        lines.append("  indices:")
        for index in indexes:
            lines.append(
                "    - "
                + "; ".join(
                    part
                    for part in (
                        f"name={_stringify(index.get('name'))}",
                        f"columns={', '.join(str(c) for c in (index.get('column_names') or []))}",
                        f"unique={_stringify(index.get('unique'))}",
                    )
                    if part
                )
            )
    else:
        lines.append("  indices: -")
    if uniques:
        lines.append("  restricoes unique:")
        for unique in uniques:
            lines.append(
                f"    - name={_stringify(unique.get('name'))}; columns={', '.join(str(c) for c in (unique.get('column_names') or []))}"
            )
    else:
        lines.append("  restricoes unique: -")
    if fks:
        lines.append("  foreign keys:")
        for fk in fks:
            lines.append(
                f"    - name={_stringify(fk.get('name'))}; columns={', '.join(str(c) for c in (fk.get('constrained_columns') or []))}; "
                f"referred_table={_stringify(fk.get('referred_table'))}; referred_columns={', '.join(str(c) for c in (fk.get('referred_columns') or []))}"
            )
    else:
        lines.append("  foreign keys: -")
    lines.append("  colunas:")
    if not columns:
        lines.append("    - nenhuma coluna introspectada")
    for column in columns:
        parts = [
            f"name={column.get('name')}",
            f"type={column.get('type')}",
            f"nullable={column.get('nullable')}",
            f"primary_key={column.get('primary_key')}",
        ]
        default = column.get("default")
        if default:
            parts.append(f"default={default}")
        lines.append("    - " + "; ".join(parts))
    return lines


def _format_api_debug_lines(api_debug: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    lines.append("[depuracao ao vivo via Telegram Bot API]")
    if not api_debug:
        lines.append("  nenhuma depuracao ao vivo foi anexada nesta exportacao")
        lines.append("")
        return lines
    lines.append("  Estes dados nao vêm do banco; foram consultados no momento do /listening pelo bot, quando a API permitiu.")
    for key in ("generated_at", "bot", "known_user_ids_total", "known_chat_ids_total", "users_queried", "chats_queried", "errors"):
        if key in api_debug:
            lines.append(f"  {key}: {_stringify(api_debug.get(key))}")
    user_chats = api_debug.get("user_chats") or []
    if user_chats:
        lines.append("  user_chats/getChat:")
        for item in user_chats:
            lines.append(f"    - {_stringify(item)}")
    chat_debug = api_debug.get("chat_debug") or []
    if chat_debug:
        lines.append("  chats/getChat/getChatMember:")
        for item in chat_debug:
            lines.append(f"    - {_stringify(item)}")
    lines.append("")
    return lines


def _format_table_dump_lines(data: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("[schema e dados integrais por tabela]")
    lines.append("  Exportacao owner-only: valores sao copiados como estao no banco, sem mascarar tokens, file_id, hash, chaves ou identificadores.")
    lines.append("  Tabelas nao mapeadas por model tambem entram se existirem no banco.")
    lines.append("")
    for table_name in sorted(data):
        item = data.get(table_name) or {"columns": [], "schema": {}, "rows": []}
        columns = list(item.get("columns") or [])
        schema = dict(item.get("schema") or {})
        rows = list(item.get("rows") or [])
        label = _TABLE_LABELS.get(table_name, "tabela existente no banco")
        lines.append(f"[{table_name}] {label} | linhas={len(rows)} | colunas={', '.join(columns) if columns else 'sem colunas'}")
        lines.extend(_format_schema_lines(table_name, schema))
        if not rows:
            lines.append("  registros: sem registros")
            lines.append("")
            continue
        lines.append("  registros:")
        for index, row in enumerate(rows, start=1):
            identifiers = _identifier_values(row, columns)
            id_suffix = f" | identificadores: {'; '.join(identifiers)}" if identifiers else ""
            lines.append(f"    #{index}{id_suffix}")
            for column in columns:
                lines.append(f"      {column}: {_stringify(row.get(column))}")
            lines.append("")
    return lines


def _build_login_export_text(generated_at: datetime, *, api_debug: dict[str, Any] | None = None) -> tuple[str, ListeningExportStats]:
    data, stats, users = _collect_listening_tables()
    lines: list[str] = []
    lines.append("TR4 /listening - exportacao administrativa integral do banco")
    lines.append(f"Gerado em UTC: {generated_at.isoformat(sep=' ')}")
    lines.append(f"Corte legacy: {LEGACY_CUTOFF.isoformat(sep=' ')} UTC")
    lines.append("")
    lines.append("Escopo do relatorio:")
    lines.append("  - exporta todas as tabelas visiveis no banco configurado, nao apenas uma lista fixa")
    lines.append("  - inclui schema, primary keys, indices, unique constraints, foreign keys quando o driver expuser")
    lines.append("  - inclui todos os valores gravados, inclusive tokens, file_id, hash, chaves, ids e demais identificadores")
    lines.append("  - resume por user_id/telegram_user_id/owner_user_id quando essas colunas existirem")
    lines.append("  - cruza nomes/usernames salvos nos updates brutos com getChat da Telegram Bot API quando possivel")
    lines.append("  - calcula primeira entrada/interacao bruta, modo de uso, comandos, chat type, drops operacionais e tabelas onde o usuario aparece")
    lines.append("  - lista tokens completos por usuario alem do dump integral da tabela")
    lines.append("  - quando o banco nao salva nome Telegram, o relatorio identifica pelo user_id e pelos dados musicais/operacionais disponiveis")
    lines.append("")
    lines.append("Totais:")
    lines.append(f"  usuarios identificados: {stats.user_count}")
    lines.append(f"  tabelas exportadas: {stats.schema_count}")
    lines.append(f"  linhas totais exportadas: {stats.row_count}")
    lines.append(f"  linhas de inscricao/login conhecidas: {stats.login_row_count}")
    lines.append(f"  linhas de interacao/uso conhecidas: {stats.interaction_row_count}")
    lines.append(f"  tabelas presentes: {', '.join(stats.present_tables) if stats.present_tables else '-'}")
    lines.append(f"  tabelas conhecidas ausentes: {', '.join(stats.known_missing_tables) if stats.known_missing_tables else '-'}")
    lines.append("")
    lines.extend(_api_debug_overview(api_debug))
    lines.extend(_format_user_summary_lines(users, api_debug=api_debug))
    lines.extend(_format_api_debug_lines(api_debug))
    lines.extend(_format_table_dump_lines(data))
    return "\n".join(lines).rstrip() + "\n", stats

def _pdf_escape(line: str) -> bytes:
    safe = line.encode("latin-1", "replace").decode("latin-1")
    safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return safe.encode("latin-1", "replace")


def _make_pdf(lines: list[str]) -> bytes:
    page_width = 595
    page_height = 842
    margin_x = 36
    start_y = 810
    line_height = 10
    max_lines = 76
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        chunks = textwrap.wrap(line, width=112, replace_whitespace=False, drop_whitespace=False) or [line]
        wrapped.extend(chunks)

    pages = [wrapped[i : i + max_lines] for i in range(0, len(wrapped), max_lines)] or [["sem dados"]]
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_ids: list[int] = []
    for page_lines in pages:
        content = bytearray()
        content.extend(f"BT /F1 8 Tf {line_height} TL {margin_x} {start_y} Td\n".encode("ascii"))
        for line in page_lines:
            content.extend(b"(")
            content.extend(_pdf_escape(line))
            content.extend(b") Tj T*\n")
        content.extend(b"ET")
        stream_id = add(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + bytes(content) + b"\nendstream")
        page_id = add(
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {page_width} {page_height}] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {stream_id} 0 R >>".encode("ascii")
        )
        page_ids.append(page_id)

    pages_id = len(objects) + 1
    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace(b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode("ascii"))
    kids = b" ".join(f"{pid} 0 R".encode("ascii") for pid in page_ids)
    add(b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode("ascii") + b" >>")
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_pos = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _bundle_from_lines(*, lines: list[str], stamp: str, stats: ListeningExportStats, suffix: str = "") -> ExportBundle:
    text_body = "\n".join(lines).rstrip() + "\n"
    name_suffix = f"-{suffix}" if suffix else ""
    return ExportBundle(
        txt_bytes=text_body.encode("utf-8"),
        pdf_bytes=_make_pdf(lines),
        txt_filename=f"tr4-listening-{stamp}{name_suffix}.txt",
        pdf_filename=f"tr4-listening-{stamp}{name_suffix}.pdf",
        row_count=stats.row_count,
        login_row_count=stats.login_row_count,
        interaction_row_count=stats.interaction_row_count,
        user_count=stats.user_count,
    )


def _split_lines_by_utf8_size(lines: list[str], max_bytes: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        line_size = len((line + "\n").encode("utf-8"))
        if current and current_size + line_size > max_bytes:
            chunks.append(current)
            current = [line]
            current_size = line_size
        else:
            current.append(line)
            current_size += line_size
    if current:
        chunks.append(current)
    return chunks or [["sem dados"]]


def build_listening_export_parts(max_document_bytes: int = MAX_TELEGRAM_DOCUMENT_BYTES, *, api_debug: dict[str, Any] | None = None) -> list[ExportBundle]:
    now = utcnow_naive()
    text_body, stats = _build_login_export_text(now, api_debug=api_debug)
    lines = text_body.splitlines()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    single = _bundle_from_lines(lines=lines, stamp=stamp, stats=stats)
    if len(single.txt_bytes) <= max_document_bytes and len(single.pdf_bytes) <= max_document_bytes:
        return [single]

    content_chunks = _split_lines_by_utf8_size(lines, max(1024, max_document_bytes - 4096))
    bundles: list[ExportBundle] = []
    total = len(content_chunks)
    for index, chunk in enumerate(content_chunks, start=1):
        prefixed = [
            f"TR4 /listening - parte {index}/{total}",
            f"Linhas exportadas do banco: {stats.row_count}",
            f"Usuarios identificados: {stats.user_count}",
            "",
            *chunk,
        ]
        bundle = _bundle_from_lines(lines=prefixed, stamp=stamp, stats=stats, suffix=f"part{index:03d}-of-{total:03d}")
        # PDF may be larger than the TXT because each page adds object overhead.
        # If that happens, split this chunk again by line count until every PDF
        # stays below Telegram's document limit.
        if len(bundle.pdf_bytes) <= max_document_bytes and len(bundle.txt_bytes) <= max_document_bytes:
            bundles.append(bundle)
            continue
        sub_chunks = [chunk]
        while sub_chunks and any(len(_make_pdf(part)) > max_document_bytes for part in sub_chunks):
            next_chunks: list[list[str]] = []
            for part in sub_chunks:
                if len(_make_pdf(part)) <= max_document_bytes or len(part) <= 1:
                    next_chunks.append(part)
                else:
                    mid = max(1, len(part) // 2)
                    next_chunks.extend([part[:mid], part[mid:]])
            if len(next_chunks) == len(sub_chunks):
                break
            sub_chunks = next_chunks
        for sub_index, sub_chunk in enumerate(sub_chunks, start=1):
            suffix = f"part{index:03d}-{sub_index:02d}-of-{total:03d}"
            sub_prefixed = [
                f"TR4 /listening - parte {index}/{total}.{sub_index}",
                f"Linhas exportadas do banco: {stats.row_count}",
                f"Usuarios identificados: {stats.user_count}",
                "",
                *sub_chunk,
            ]
            bundles.append(_bundle_from_lines(lines=sub_prefixed, stamp=stamp, stats=stats, suffix=suffix))
    return bundles


def build_listening_export() -> ExportBundle:
    return build_listening_export_parts()[0]
