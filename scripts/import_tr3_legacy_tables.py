#!/usr/bin/env python3
"""Importador seguro de tabelas legadas TR3/TR4 para o banco persistente atual.

Uso recomendado:
  python scripts/import_tr3_legacy_tables.py --source ./app.db --target /data/app.db
  python scripts/import_tr3_legacy_tables.py --source ./app.db --target /data/app.db --apply

Características:
- dry-run é o padrão;
- recusa source == target;
- cria backup do target antes de escrever;
- usa INSERT OR IGNORE por chave/linha para não duplicar;
- importa apenas tabelas legadas conhecidas e existentes;
- grava relatório em tr3_legacy_import_runs quando --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

SAFE_TABLES = (
    "lastfm_profiles",
    "spotify_tokens",
    "track_plays",
    "track_likes",
    "track_reactions",
    "reaction_audit",
    "canvas_files",
    "card_messages",
    "new_member_watch",
    "radio_drafts",
    "radio_templates",
    "radio_schedules",
    "radio_post_history",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


@dataclass
class TableReport:
    table: str
    source_rows: int = 0
    target_rows_before: int = 0
    target_rows_after: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    skipped_missing_target: bool = False
    skipped_missing_source: bool = False
    skipped_no_common_columns: bool = False
    columns_used: list[str] = field(default_factory=list)


@dataclass
class LegacyImportReport:
    source: str
    target: str
    dry_run: bool
    tables_requested: list[str]
    backup_path: str = ""
    same_file_noop: bool = False
    target_existing_tables: dict[str, int | None] = field(default_factory=dict)
    tables: list[TableReport] = field(default_factory=list)


def _path_is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".tr4_import_probe_", dir=str(path), delete=True) as handle:
            handle.write(b"ok")
        return True
    except Exception:
        return False


def _default_target_path() -> Path:
    volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if volume:
        return Path(volume).expanduser().resolve() / "app.db"
    data_dir = Path("/data")
    if _path_is_writable_dir(data_dir):
        return data_dir.resolve() / "app.db"
    return Path("data/app.db").expanduser().resolve()


def resolve_sqlite_path(value: str | None, default: str | None = None) -> Path:
    raw = value or os.getenv("TR3_DATABASE_URL") or os.getenv("DATABASE_URL") or default
    if not raw:
        return _default_target_path()
    if raw.startswith("sqlite+aiosqlite:///"):
        raw = raw[len("sqlite+aiosqlite:///") - 1 :]
    elif raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///") - 1 :]
    elif raw.startswith("sqlite://"):
        raw = raw[len("sqlite://") :]
    return Path(unquote(raw)).expanduser().resolve()


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"Banco não encontrado: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"identificador inseguro: {name}")
    return '"' + name.replace('"', '""') + '"'


def ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tr3_legacy_import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            dry_run INTEGER NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )



def count_existing_tables(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in tables:
        if not table_exists(conn, table):
            counts[table] = None
            continue
        try:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])
        except sqlite3.DatabaseError:
            counts[table] = None
    return counts

def backup_target(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = target.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{target.name}.before_tr3_legacy_import_{stamp}.bak"
    shutil.copy2(target, backup)
    return backup


def row_signature(row: sqlite3.Row, columns: list[str]) -> tuple[object, ...]:
    return tuple(row[col] for col in columns)


def import_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, *, dry_run: bool) -> TableReport:
    report = TableReport(table=table)
    if not table_exists(src, table):
        report.skipped_missing_source = True
        return report
    if not table_exists(dst, table):
        report.skipped_missing_target = True
        return report
    src_cols = table_columns(src, table)
    dst_cols = table_columns(dst, table)
    common = [col for col in src_cols if col in set(dst_cols)]
    if not common:
        report.skipped_no_common_columns = True
        return report
    report.columns_used = common
    qt = quote_ident(table)
    select_cols = ", ".join(quote_ident(col) for col in common)
    report.source_rows = int(src.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0])
    report.target_rows_before = int(dst.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0])
    rows = list(src.execute(f"SELECT {select_cols} FROM {qt}"))

    existing_signatures: set[tuple[object, ...]] = set()
    try:
        for row in dst.execute(f"SELECT {select_cols} FROM {qt}"):
            existing_signatures.add(row_signature(row, common))
    except sqlite3.DatabaseError:
        existing_signatures = set()

    placeholders = ", ".join("?" for _ in common)
    insert_sql = f"INSERT OR IGNORE INTO {qt} ({select_cols}) VALUES ({placeholders})"
    for row in rows:
        sig = row_signature(row, common)
        if sig in existing_signatures:
            report.skipped_existing += 1
            continue
        report.inserted += 1
        existing_signatures.add(sig)
        if not dry_run:
            dst.execute(insert_sql, tuple(row[col] for col in common))
    if not dry_run:
        report.target_rows_after = int(dst.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0])
    else:
        report.target_rows_after = report.target_rows_before + report.inserted
    return report


def run_import(source: Path, target: Path, *, dry_run: bool, tables: list[str], allow_same_file: bool = False) -> LegacyImportReport:
    requested = [table for table in tables if table in SAFE_TABLES]
    report = LegacyImportReport(str(source), str(target), dry_run=dry_run, tables_requested=requested)
    if source == target:
        if not allow_same_file:
            raise RuntimeError("source e target são o mesmo arquivo. Use --allow-same-file apenas para auditar banco já consolidado.")
        conn = connect(target)
        try:
            report.same_file_noop = True
            report.target_existing_tables = count_existing_tables(conn, requested)
            for table in requested:
                count = report.target_existing_tables.get(table)
                report.tables.append(TableReport(table=table, source_rows=int(count or 0), target_rows_before=int(count or 0), target_rows_after=int(count or 0), skipped_existing=int(count or 0)))
        finally:
            conn.close()
        return report
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(str(target)).close()
    if not dry_run:
        report.backup_path = str(backup_target(target))

    src = connect(source)
    dst = connect(target)
    try:
        ensure_audit_table(dst)
        for table in requested:
            report.tables.append(import_table(src, dst, table, dry_run=dry_run))
        report.target_existing_tables = count_existing_tables(dst, requested)
        if not dry_run:
            dst.execute(
                """
                INSERT INTO tr3_legacy_import_runs (created_at, source_path, target_path, dry_run, report_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utcnow(), str(source), str(target), int(dry_run), json.dumps(asdict(report), ensure_ascii=False)),
            )
            dst.commit()
    finally:
        src.close()
        dst.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importa tabelas legadas TR3 para o banco TR4 com dry-run, backup e idempotência.")
    parser.add_argument("--source", required=True, help="Banco SQLite antigo recuperado, ex.: ./app.db")
    parser.add_argument("--target", default=None, help="Banco SQLite atual. Default: TR3_DATABASE_URL, DATABASE_URL, RAILWAY_VOLUME_MOUNT_PATH/app.db, /data/app.db ou data/app.db")
    parser.add_argument("--allow-same-file", action="store_true", help="Audita source==target como banco já consolidado, sem escrita.")
    parser.add_argument("--apply", action="store_true", help="Executa escrita. Sem isso, roda dry-run.")
    parser.add_argument("--tables", default=",".join(SAFE_TABLES), help="Lista separada por vírgula; padrão: tabelas seguras conhecidas")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source).expanduser().resolve()
    target = resolve_sqlite_path(args.target)
    tables = [part.strip() for part in str(args.tables or "").split(",") if part.strip()]
    try:
        report = run_import(source, target, dry_run=not args.apply, tables=tables, allow_same_file=bool(args.allow_same_file))
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
