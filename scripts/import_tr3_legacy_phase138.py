#!/usr/bin/env python3
"""Fase 138 — importação idempotente do banco legado TR3.

Uso obrigatório em produção:

    python scripts/import_tr3_legacy_phase138.py --source /caminho/tr3_antigo.db --target /data/app.db --apply

Sem ``--apply`` o script executa dry-run e não altera o banco alvo.

Regras implementadas:
- source e target são sempre explícitos;
- source precisa existir;
- source == target é recusado;
- backup do source e do target antes de escrita;
- importação em transação única;
- marcador idempotente ``tr3_legacy_import_applied`` em ``import_markers``;
- segunda execução com o mesmo source vira noop e não duplica;
- marcador com fingerprint diferente aborta para evitar mistura insegura;
- tabelas legadas ausentes no target podem ser criadas a partir do schema do source;
- INSERT OR IGNORE + assinatura de linha evita duplicação de tabelas sem chave única.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
RUNS_TABLE = "tr3_legacy_import_runs"
MARKER_KEY = "tr3_legacy_import_applied"


@dataclass
class TableImportReport:
    table: str
    source_exists: bool = False
    target_existed_before: bool = False
    target_created: bool = False
    source_rows: int = 0
    target_rows_before: int = 0
    target_rows_after: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    skipped_no_common_columns: bool = False
    columns_used: list[str] = field(default_factory=list)


@dataclass
class Phase138ImportReport:
    ok: bool
    dry_run: bool
    source: str
    target: str
    marker_key: str = MARKER_KEY
    source_sha256: str = ""
    source_backup: str = ""
    target_backup: str = ""
    marker_existing: bool = False
    marker_noop: bool = False
    marker_created: bool = False
    started_at: str = ""
    finished_at: str = ""
    before_counts: dict[str, int | None] = field(default_factory=dict)
    after_counts: dict[str, int | None] = field(default_factory=dict)
    tables: list[TableImportReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"identificador inseguro: {name}")
    return '"' + name.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def connect_existing(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"banco não encontrado: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def ensure_target_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        sqlite3.connect(str(path)).close()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def table_counts(conn: sqlite3.Connection, tables: tuple[str, ...] = LEGACY_TABLES) -> dict[str, int | None]:
    return {table: table_count(conn, table) for table in tables}


def source_create_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not row or not row[0]:
        return None
    sql = str(row[0]).strip()
    if not sql.upper().startswith("CREATE TABLE"):
        return None
    return sql


def ensure_marker_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quote_ident(MARKER_TABLE)} (
            marker_key TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            source_path TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quote_ident(RUNS_TABLE)} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            dry_run INTEGER NOT NULL,
            marker_key TEXT NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )


def load_marker(conn: sqlite3.Connection, marker_key: str = MARKER_KEY) -> sqlite3.Row | None:
    if not table_exists(conn, MARKER_TABLE):
        return None
    return conn.execute(
        f"SELECT marker_key, source_sha256, source_path, applied_at FROM {quote_ident(MARKER_TABLE)} WHERE marker_key=? LIMIT 1",
        (marker_key,),
    ).fetchone()


def backup_file(path: Path, backup_root: Path, label: str) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_root / f"{path.name}.{label}.{stamp}.bak"
    shutil.copy2(path, backup)
    return backup


def row_signature(row: sqlite3.Row, columns: list[str]) -> tuple[object, ...]:
    return tuple(row[col] for col in columns)


def create_missing_target_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> bool:
    sql = source_create_sql(src, table)
    if not sql:
        return False
    dst.execute(sql)
    return True


def import_one_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, *, create_missing: bool) -> TableImportReport:
    report = TableImportReport(table=table)
    report.source_exists = table_exists(src, table)
    if not report.source_exists:
        return report

    report.target_existed_before = table_exists(dst, table)
    if not report.target_existed_before and create_missing:
        report.target_created = create_missing_target_table(src, dst, table)
    if not table_exists(dst, table):
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

    existing: set[tuple[object, ...]] = set()
    for row in dst.execute(f"SELECT {select_cols} FROM {qt}"):
        existing.add(row_signature(row, common))

    placeholders = ", ".join("?" for _ in common)
    insert_sql = f"INSERT OR IGNORE INTO {qt} ({select_cols}) VALUES ({placeholders})"
    for row in src.execute(f"SELECT {select_cols} FROM {qt}"):
        sig = row_signature(row, common)
        if sig in existing:
            report.skipped_existing += 1
            continue
        before = dst.total_changes
        dst.execute(insert_sql, tuple(row[col] for col in common))
        if dst.total_changes > before:
            report.inserted += 1
            existing.add(sig)
        else:
            report.skipped_existing += 1

    report.target_rows_after = int(dst.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0])
    return report


def run_phase138_import(
    source: Path,
    target: Path,
    *,
    apply: bool = False,
    tables: tuple[str, ...] = LEGACY_TABLES,
    backup_dir: Path | None = None,
    create_missing_tables: bool = True,
) -> Phase138ImportReport:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"source não existe: {source}")
    if source == target:
        raise RuntimeError("source e target são o mesmo arquivo; importação recusada")

    ensure_target_file(target)
    fingerprint = sha256_file(source)
    backup_root = backup_dir.expanduser().resolve() if backup_dir else target.parent / "phase138_backups"

    report = Phase138ImportReport(
        ok=True,
        dry_run=not apply,
        source=str(source),
        target=str(target),
        source_sha256=fingerprint,
        started_at=utc_now(),
    )

    src = connect_existing(source)
    dst = connect_existing(target)
    try:
        ensure_marker_tables(dst)
        marker = load_marker(dst)
        report.before_counts = table_counts(dst, tables)
        if marker:
            report.marker_existing = True
            marker_hash = str(marker["source_sha256"] or "")
            if marker_hash != fingerprint:
                raise RuntimeError(
                    "marcador tr3_legacy_import_applied já existe com fingerprint diferente; "
                    "abortando para evitar importação incompatível"
                )
            report.marker_noop = True
            report.after_counts = report.before_counts.copy()
            report.finished_at = utc_now()
            return report

        if not apply:
            # Dry-run: simula tabelas, mas não cria backup nem escreve no target.
            for table in tables:
                t = TableImportReport(table=table, source_exists=table_exists(src, table), target_existed_before=table_exists(dst, table))
                if t.source_exists:
                    t.source_rows = table_count(src, table) or 0
                if t.target_existed_before:
                    t.target_rows_before = table_count(dst, table) or 0
                    t.target_rows_after = t.target_rows_before
                report.tables.append(t)
            report.after_counts = report.before_counts.copy()
            report.finished_at = utc_now()
            return report

        report.source_backup = str(backup_file(source, backup_root, "source_before_import"))
        report.target_backup = str(backup_file(target, backup_root, "target_before_import"))

        try:
            dst.execute("BEGIN")
            for table in tables:
                report.tables.append(import_one_table(src, dst, table, create_missing=create_missing_tables))
            report.after_counts = table_counts(dst, tables)
            marker_payload = json.dumps(asdict(report), ensure_ascii=False, sort_keys=True)
            dst.execute(
                f"""
                INSERT INTO {quote_ident(MARKER_TABLE)} (marker_key, source_sha256, source_path, applied_at, report_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (MARKER_KEY, fingerprint, str(source), utc_now(), marker_payload),
            )
            report.marker_created = True
            report.finished_at = utc_now()
            final_payload = json.dumps(asdict(report), ensure_ascii=False, sort_keys=True)
            dst.execute(
                f"""
                INSERT INTO {quote_ident(RUNS_TABLE)} (created_at, source_path, target_path, source_sha256, dry_run, marker_key, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), str(source), str(target), fingerprint, 0, MARKER_KEY, final_payload),
            )
            # Atualiza o report_json do marker para incluir after_counts/finalizado.
            dst.execute(
                f"UPDATE {quote_ident(MARKER_TABLE)} SET report_json=? WHERE marker_key=?",
                (final_payload, MARKER_KEY),
            )
            dst.commit()
        except Exception:
            dst.rollback()
            raise
        return report
    finally:
        src.close()
        dst.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fase 138: importa legado TR3 para /data/app.db com backup, transação e marcador idempotente.")
    parser.add_argument("--source", required=True, help="Banco SQLite legado TR3. Obrigatório e explícito.")
    parser.add_argument("--target", required=True, help="Banco SQLite alvo atual, normalmente /data/app.db. Obrigatório e explícito.")
    parser.add_argument("--apply", action="store_true", help="Aplica escrita. Sem isso roda dry-run.")
    parser.add_argument("--backup-dir", default=None, help="Diretório para backups. Padrão: <target_dir>/phase138_backups")
    parser.add_argument("--no-create-missing-tables", action="store_true", help="Não cria tabelas legadas ausentes no target.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_phase138_import(
            Path(args.source),
            Path(args.target),
            apply=bool(args.apply),
            backup_dir=Path(args.backup_dir) if args.backup_dir else None,
            create_missing_tables=not bool(args.no_create_missing_tables),
        )
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
