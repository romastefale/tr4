from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text

from app.db.database import SessionLocal, engine
from app.utils.datetime import utcnow_naive

logger = logging.getLogger(__name__)

LEGACY_CUTOFF = datetime(2026, 6, 15, 0, 0, 0)
SILENT_MODE_KEY = "silent_mode_enabled"
LEGACY_MODE_KEY = "legacy_mode_enabled"
MAX_TELEGRAM_DOCUMENT_BYTES = 45 * 1024 * 1024
_ALLOWED_DURING_SILENT = {"start", "help"}
_ALLOWED_FOR_LEGACY_RELOGIN = {"start", "help", "login", "lastfm"}
_LOGIN_TABLES = ("lastfm_profiles", "spotify_tokens")
_INTERACTION_TABLES = (
    "tnow_recent_tracks",
    "track_plays",
    "track_reactions",
    "track_likes",
    "card_messages",
    "tnow_private_visibility",
)
_LISTENING_EXPORT_TABLES = (*_LOGIN_TABLES, "legacy_restricted_users", *_INTERACTION_TABLES)
_USER_ID_COLUMNS = ("user_id", "telegram_user_id", "owner_user_id", "created_by_owner_id")
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
)
_TABLE_LABELS = {
    "lastfm_profiles": "inscricao Last fm",
    "spotify_tokens": "inscricao Spotify",
    "legacy_restricted_users": "estado legacy",
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
    missing_tables: tuple[str, ...] = field(default_factory=tuple)


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


def _table_rows(table_name: str) -> tuple[list[str], list[dict[str, Any]]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if table_name not in tables:
        return [], []
    columns = [column["name"] for column in inspector.get_columns(table_name)]
    if not columns:
        return [], []
    order_column = "user_id" if "user_id" in columns else "telegram_user_id" if "telegram_user_id" in columns else columns[0]
    table_sql = _quote_identifier(table_name)
    order_sql = _quote_identifier(order_column)
    with SessionLocal() as db:
        rows = db.execute(text(f"SELECT * FROM {table_sql} ORDER BY {order_sql}")).mappings().all()
        return columns, [dict(row) for row in rows]


def _try_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _try_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
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


def _row_user_roles(row: dict[str, Any], columns: list[str]) -> list[tuple[str, int]]:
    roles: list[tuple[str, int]] = []
    for column in _USER_ID_COLUMNS:
        if column not in columns:
            continue
        user_id = _try_int(row.get(column))
        if user_id is not None:
            roles.append((column, user_id))
    return roles


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
        },
    )
    user["tables"].add(table_name)
    user["roles"].add(f"{table_name}.{role}")
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
    elif table_name == "spotify_tokens":
        user["spotify_connected"] = True
        if row.get("expiration"):
            user["spotify_expirations"].append(_stringify(row.get("expiration")))
    elif table_name == "legacy_restricted_users":
        user["legacy_status"] = "liberado" if row.get("released_at") else "ativo"
    elif table_name == "tnow_private_visibility":
        user["tpv_rules"].append(
            f"mode={_stringify(row.get('mode')) or '-'}; label={_stringify(row.get('display_label')) or '-'}; enabled={_stringify(row.get('enabled')) or '-'}"
        )
    elif table_name in {"tnow_recent_tracks", "track_plays", "track_likes", "track_reactions"}:
        track = _compact_track(row)
        if track:
            when = row.get("played_at") or row.get("observed_at") or row.get("created_at") or row.get("updated_at")
            user["latest_tracks"].append((_stringify(when), table_name, track))


def _collect_listening_tables() -> tuple[dict[str, dict[str, Any]], ListeningExportStats, dict[int, dict[str, Any]]]:
    data: dict[str, dict[str, Any]] = {}
    users: dict[int, dict[str, Any]] = {}
    present: list[str] = []
    missing: list[str] = []
    total_rows = 0
    login_rows = 0
    interaction_rows = 0

    for table_name in _LISTENING_EXPORT_TABLES:
        columns, rows = _table_rows(table_name)
        exists = bool(columns)
        if exists:
            present.append(table_name)
        else:
            missing.append(table_name)
        data[table_name] = {"columns": columns, "rows": rows}
        total_rows += len(rows)
        if table_name in _LOGIN_TABLES:
            login_rows += len(rows)
        elif table_name in _INTERACTION_TABLES:
            interaction_rows += len(rows)
        for row in rows:
            for role, user_id in _row_user_roles(row, columns):
                _add_user_fact(users, user_id, table_name=table_name, role=role, row=row)

    stats = ListeningExportStats(
        row_count=total_rows,
        login_row_count=login_rows,
        interaction_row_count=interaction_rows,
        user_count=len(users),
        present_tables=tuple(present),
        missing_tables=tuple(missing),
    )
    return data, stats, users


def _format_user_summary_lines(users: dict[int, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("[resumo por usuario identificado]")
    if not users:
        lines.append("  nenhum usuario identificado nas tabelas exportadas")
        lines.append("")
        return lines

    for user_id in sorted(users):
        user = users[user_id]
        lines.append(f"  usuario_id: {user_id}")
        usernames = sorted(user["lastfm_usernames"])
        lines.append(f"    Last fm usernames: {', '.join(usernames) if usernames else '-'}")
        spotify_exp = sorted(set(user["spotify_expirations"]))
        spotify_text = "sim" if user["spotify_connected"] else "nao"
        if spotify_exp:
            spotify_text += f"; expiracoes={', '.join(spotify_exp[-3:])}"
        lines.append(f"    Spotify conectado: {spotify_text}")
        lines.append(f"    legacy: {user['legacy_status']}")
        lines.append(f"    primeira data vista no banco: {_stringify(user.get('first_seen')) or '-'}")
        lines.append(f"    ultima data vista no banco: {_stringify(user.get('last_seen')) or '-'}")
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
        lines.append("")
    return lines


def _format_table_dump_lines(data: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("[dados integrais por tabela]")
    lines.append("  Observacao: o TXT e o PDF abaixo copiam os valores existentes no banco para as tabelas exportadas.")
    lines.append("")
    for table_name in _LISTENING_EXPORT_TABLES:
        item = data.get(table_name) or {"columns": [], "rows": []}
        columns = list(item.get("columns") or [])
        rows = list(item.get("rows") or [])
        label = _TABLE_LABELS.get(table_name, table_name)
        lines.append(f"[{table_name}] {label} | linhas={len(rows)} | colunas={', '.join(columns) if columns else 'tabela ausente'}")
        if not rows:
            lines.append("  sem registros")
            lines.append("")
            continue
        for index, row in enumerate(rows, start=1):
            lines.append(f"  #{index}")
            for column in columns:
                lines.append(f"    {column}: {_stringify(row.get(column))}")
            lines.append("")
    return lines


def _build_login_export_text(generated_at: datetime) -> tuple[str, ListeningExportStats]:
    data, stats, users = _collect_listening_tables()
    lines: list[str] = []
    lines.append("TR4 /listening - relatorio integral de inscricoes e interacoes")
    lines.append(f"Gerado em UTC: {generated_at.isoformat(sep=' ')}")
    lines.append(f"Corte legacy: {LEGACY_CUTOFF.isoformat(sep=' ')} UTC")
    lines.append("")
    lines.append("Escopo do relatorio:")
    lines.append("  - inscricoes/login salvos: lastfm_profiles, spotify_tokens")
    lines.append("  - estado operacional: legacy_restricted_users")
    lines.append("  - interacoes identificaveis pelo banco: tnow_recent_tracks, track_plays, track_reactions, track_likes, card_messages, tnow_private_visibility")
    lines.append("  - quando o banco nao salva nome Telegram, o relatorio identifica pelo user_id e pelos dados musicais/operacionais disponiveis")
    lines.append("")
    lines.append("Totais:")
    lines.append(f"  usuarios identificados: {stats.user_count}")
    lines.append(f"  linhas totais exportadas: {stats.row_count}")
    lines.append(f"  linhas de inscricao/login: {stats.login_row_count}")
    lines.append(f"  linhas de interacao/uso: {stats.interaction_row_count}")
    lines.append(f"  tabelas presentes: {', '.join(stats.present_tables) if stats.present_tables else '-'}")
    lines.append(f"  tabelas ausentes: {', '.join(stats.missing_tables) if stats.missing_tables else '-'}")
    lines.append("")
    lines.extend(_format_user_summary_lines(users))
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


def build_listening_export_parts(max_document_bytes: int = MAX_TELEGRAM_DOCUMENT_BYTES) -> list[ExportBundle]:
    now = utcnow_naive()
    text_body, stats = _build_login_export_text(now)
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
