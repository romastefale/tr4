from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import DATABASE_URL
from sqlalchemy.engine import make_url
from app.db.database import engine as default_engine

logger = logging.getLogger(__name__)

PERSISTENCE_CRITICAL_TABLES: tuple[str, ...] = (
    "lastfm_profiles",
    "spotify_tokens",
    "track_plays",
    "track_likes",
    "track_reactions",
    "reaction_audit",
    "eq_operadores",
    "eq_runtime_grants",
    "eq_private_sessions",
    "eq_security_mode",
    "eq_security_audit",
    "eq_radio_drafts",
    "eq_multimedia_sessions",
    "eq_ddx_events",
    "tr3_legacy_import_runs",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar() is not None


def _count(conn, table: str) -> int | None:
    if not _table_exists(conn, table):
        return None
    return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def ensure_persistence_state(db_engine: Engine = default_engine) -> dict[str, object]:
    """Persist and return a non-sensitive persistence heartbeat.

    This makes restart/deploy checks factual without logging absolute database
    paths or operator identifiers. The table itself lives in the active DB, so
    if it survives deploys, the active DB is persistent.
    """
    data_dir = str(getattr(settings, "DATA_DIR", ""))
    db_path = ""
    try:
        db_path = str(make_url(DATABASE_URL).database or "")
    except Exception:
        db_path = ""
    under_volume = (
        data_dir == "/data"
        or data_dir.startswith("/data/")
        or db_path == "/data/app.db"
        or db_path.startswith("/data/")
    )
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_persistence_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        now = _now()
        conn.execute(
            text("""
                INSERT INTO eq_persistence_state (key, value, updated_at)
                VALUES ('startup_heartbeat', :value, :updated_at)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """),
            {"value": "volume" if under_volume else "container", "updated_at": now},
        )
        counts = {table: _count(conn, table) for table in PERSISTENCE_CRITICAL_TABLES}
    warnings = [] if under_volume else ["banco_fora_do_volume_persistente"]
    report: dict[str, object] = {
        "ok": not warnings,
        "local": "volume" if under_volume else "container",
        "persistente": under_volume,
        "tabelas": counts,
        "alertas": warnings,
    }
    if warnings:
        logger.warning("TR4_PERSISTENCE_GUARD_WARNING local=%s warnings=%s", report["local"], ",".join(warnings))
    else:
        logger.info("TR4_PERSISTENCE_GUARD_OK local=volume")
    return report
