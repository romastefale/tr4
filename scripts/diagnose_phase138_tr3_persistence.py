#!/usr/bin/env python3
"""Fase 138 — diagnóstico factual de persistência TR3/TR4.

Não altera banco. Mostra caminho real, existência de /data/app.db, tabelas,
contagens, marcador de importação e fingerprint opcional da base legada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

LEGACY_TABLES: tuple[str, ...] = (
    "lastfm_profiles",
    "spotify_tokens",
    "track_plays",
    "track_likes",
    "track_reactions",
    "reaction_audit",
    "canvas_files",
    "card_messages",
    "new_member_watch",
)

MARKER_TABLE = "import_markers"
MARKER_KEY = "tr3_legacy_import_applied"
EXTRA_TABLES: tuple[str, ...] = ("schema_migrations", "app_markers", "import_markers", "settings", "tr3_legacy_import_runs", "eq_private_sessions")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode_sqlite_url(raw: str) -> str:
    if raw.startswith("sqlite+aiosqlite:///"):
        return raw[len("sqlite+aiosqlite:///") - 1 :]
    if raw.startswith("sqlite:///"):
        return raw[len("sqlite:///") - 1 :]
    if raw.startswith("sqlite://"):
        return raw[len("sqlite://") :]
    return raw


def resolve_target(explicit: str | None) -> Path:
    raw = (explicit or "").strip()
    if not raw:
        raw = (os.getenv("TR3_DATABASE_URL") or "").strip()
    if not raw:
        legacy = (os.getenv("DATABASE_URL") or "").strip()
        if legacy.startswith("sqlite"):
            raw = legacy
    if raw:
        return Path(unquote(_decode_sqlite_url(raw))).expanduser().resolve()
    return Path("/data/app.db").resolve()


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def count_table(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    safe = '"' + table.replace('"', '""') + '"'
    return int(conn.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()[0])


def list_tables(conn: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def read_marker(conn: sqlite3.Connection) -> dict[str, object] | None:
    if not table_exists(conn, MARKER_TABLE):
        return None
    row = conn.execute(
        "SELECT marker_key, source_sha256, source_path, applied_at FROM import_markers WHERE marker_key=? LIMIT 1",
        (MARKER_KEY,),
    ).fetchone()
    if not row:
        return None
    return {"marker_key": row[0], "source_sha256": row[1], "source_path": row[2], "applied_at": row[3]}


def diagnose(target: Path, source: Path | None = None) -> dict[str, object]:
    data_path = Path("/data")
    target_exists = target.exists()
    report: dict[str, object] = {
        "ok": False,
        "checked_at": utc_now(),
        "target": str(target),
        "target_exists": target_exists,
        "target_size_bytes": target.stat().st_size if target_exists else 0,
        "expected_data_db_exists": Path("/data/app.db").exists(),
        "expected_data_db_size_bytes": Path("/data/app.db").stat().st_size if Path("/data/app.db").exists() else 0,
        "under_data_volume": str(target).startswith("/data/"),
        "data_dir_exists": data_path.exists(),
        "data_dir_writable_probe": False,
        "railway_volume_mount_path": os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ""),
        "tr3_database_url_set": bool(os.getenv("TR3_DATABASE_URL")),
        "database_url_sqlite": (os.getenv("DATABASE_URL") or "").startswith("sqlite"),
        "source": str(source) if source else "",
        "source_exists": bool(source and source.exists()),
        "source_size_bytes": source.stat().st_size if source and source.exists() else 0,
        "source_sha256": sha256_file(source) if source else None,
        "tables": {},
        "table_names": [],
        "marker": None,
        "warnings": [],
    }
    warnings: list[str] = report["warnings"]  # type: ignore[assignment]

    try:
        data_path.mkdir(parents=True, exist_ok=True)
        probe = data_path / ".phase138_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        report["data_dir_writable_probe"] = True
    except Exception:
        warnings.append("data_dir_not_writable")

    if not target_exists:
        warnings.append("target_not_found")
        return report
    if not str(target).startswith("/data/"):
        warnings.append("target_not_under_data")

    try:
        with sqlite3.connect(str(target)) as conn:
            conn.row_factory = sqlite3.Row
            report["table_names"] = list_tables(conn)
            counts: dict[str, int | None] = {}
            for table in LEGACY_TABLES + EXTRA_TABLES:
                counts[table] = count_table(conn, table)
            report["tables"] = counts
            report["marker"] = read_marker(conn)
            if not report["marker"]:
                warnings.append("phase138_marker_missing")
            for table in LEGACY_TABLES:
                if counts.get(table) is None:
                    warnings.append(f"missing_table:{table}")
    except sqlite3.DatabaseError as exc:
        warnings.append(f"sqlite_error:{type(exc).__name__}")
        return report

    report["ok"] = not warnings
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnostica persistência real da Fase 138 sem alterar banco.")
    parser.add_argument("--target", default=None, help="Banco alvo. Padrão: TR3_DATABASE_URL, DATABASE_URL sqlite, ou /data/app.db")
    parser.add_argument("--source", default=None, help="Banco legado TR3 opcional para fingerprint/comparação de existência.")
    parser.add_argument("--strict", action="store_true", help="Retorna 1 se houver warnings.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = resolve_target(args.target)
    source = Path(args.source).expanduser().resolve() if args.source else None
    report = diagnose(target, source)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
