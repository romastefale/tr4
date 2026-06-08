#!/usr/bin/env python3
"""Audita se o TR4 está usando banco SQLite persistente.

Uso:
  python scripts/persistence_guard.py
  python scripts/persistence_guard.py --strict
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import unquote

IMPORTANT_TABLES = (
    "lastfm_profiles",
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
    "eq_persistence_state",
    "tr3_legacy_import_runs",
    "import_markers",
)


def resolve_db_path() -> Path:
    raw = os.getenv("TR3_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    if raw.startswith("sqlite+aiosqlite:///"):
        raw = raw[len("sqlite+aiosqlite:///") - 1 :]
    elif raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///") - 1 :]
    elif raw.startswith("sqlite://"):
        raw = raw[len("sqlite://") :]
    if raw:
        return Path(unquote(raw)).expanduser().resolve()
    volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "/data"
    return Path(volume).expanduser().resolve() / "app.db"


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        return None
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def audit() -> dict[str, object]:
    db_path = resolve_db_path()
    result: dict[str, object] = {
        "database_path": str(db_path),
        "exists": db_path.exists(),
        "under_data": str(db_path).startswith("/data/"),
        "railway_volume_mount_path": os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ""),
        "tables": {},
        "ok": False,
        "warnings": [],
    }
    warnings: list[str] = result["warnings"]  # type: ignore[assignment]
    if not db_path.exists():
        warnings.append("database_path_not_found")
        return result
    if not str(db_path).startswith("/data/"):
        warnings.append("database_not_under_data_volume")
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            tables: dict[str, int | None] = {}
            missing = []
            for table in IMPORTANT_TABLES:
                tables[table] = table_count(conn, table)
                if tables[table] is None:
                    missing.append(table)
            result["tables"] = tables
            if missing:
                warnings.append("missing_tables:" + ",".join(missing))
    except sqlite3.DatabaseError as exc:
        warnings.append(f"sqlite_error:{type(exc).__name__}")
        return result
    result["ok"] = not warnings
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita persistência SQLite do TR4.")
    parser.add_argument("--strict", action="store_true", help="Retorna código 1 quando houver warnings.")
    args = parser.parse_args()
    report = audit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
