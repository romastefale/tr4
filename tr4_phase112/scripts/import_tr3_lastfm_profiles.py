#!/usr/bin/env python3
"""Importador seguro de perfis Last.fm do banco TR3 para o banco TR4.

Uso típico:
  python scripts/import_tr3_lastfm_profiles.py --source ./app.db --target /data/app.db --dry-run
  python scripts/import_tr3_lastfm_profiles.py --source ./app.db --target /data/app.db --apply

Regras de segurança:
- dry-run é o padrão;
- nunca sobrescreve usuário existente sem --overwrite;
- cria backup do target antes de escrever;
- é idempotente;
- grava relatório em tr3_import_runs no banco de destino quando --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-.]{2,64}$")
REQUIRED_COLUMNS = {"user_id", "username", "created_at", "updated_at"}


@dataclass
class ImportReport:
    source: str
    target: str
    dry_run: bool
    overwrite: bool
    source_rows: int = 0
    target_existing: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    backup_path: str = ""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def resolve_sqlite_path(value: str | None, default: str = "data/app.db") -> Path:
    raw = value or os.getenv("DATABASE_URL") or default
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


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_target_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_profiles (
            user_id INTEGER PRIMARY KEY,
            username VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lastfm_profiles_user_id ON lastfm_profiles (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lastfm_profiles_username ON lastfm_profiles (username)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tr3_import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            dry_run INTEGER NOT NULL,
            overwrite INTEGER NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )


def validate_source(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lastfm_profiles'"
    ).fetchone()
    if not exists:
        raise RuntimeError("Tabela lastfm_profiles não encontrada no banco de origem")
    missing = REQUIRED_COLUMNS - table_columns(conn, "lastfm_profiles")
    if missing:
        raise RuntimeError(f"Tabela lastfm_profiles sem colunas obrigatórias: {sorted(missing)}")


def clean_username(username: object) -> str | None:
    value = str(username or "").strip().lstrip("@")
    if not value or not USERNAME_RE.match(value):
        return None
    return value


def backup_target(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = target.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{target.name}.before_tr3_lastfm_import_{stamp}.bak"
    shutil.copy2(target, backup)
    return backup


def import_profiles(source: Path, target: Path, *, dry_run: bool, overwrite: bool) -> ImportReport:
    report = ImportReport(str(source), str(target), dry_run=dry_run, overwrite=overwrite)
    src = connect(source)
    try:
        validate_source(src)
        rows = list(
            src.execute(
                """
                SELECT user_id, username, created_at, updated_at
                FROM lastfm_profiles
                ORDER BY user_id
                """
            )
        )
    finally:
        src.close()
    report.source_rows = len(rows)

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(str(target)).close()

    if not dry_run:
        report.backup_path = str(backup_target(target))

    dst = sqlite3.connect(str(target))
    dst.row_factory = sqlite3.Row
    try:
        ensure_target_schema(dst)
        report.target_existing = int(dst.execute("SELECT COUNT(*) FROM lastfm_profiles").fetchone()[0])
        for row in rows:
            try:
                user_id = int(row["user_id"])
                username = clean_username(row["username"])
                if not username:
                    report.skipped_invalid += 1
                    continue
                created_at = str(row["created_at"] or utcnow())
                updated_at = str(row["updated_at"] or created_at)
                existing = dst.execute(
                    "SELECT username FROM lastfm_profiles WHERE user_id=?", (user_id,)
                ).fetchone()
                if existing:
                    if overwrite and str(existing["username"]) != username:
                        report.updated += 1
                        if not dry_run:
                            dst.execute(
                                "UPDATE lastfm_profiles SET username=?, updated_at=? WHERE user_id=?",
                                (username, updated_at, user_id),
                            )
                    else:
                        report.skipped_existing += 1
                    continue
                report.inserted += 1
                if not dry_run:
                    dst.execute(
                        """
                        INSERT INTO lastfm_profiles (user_id, username, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (user_id, username, created_at, updated_at),
                    )
            except Exception:
                report.errors += 1
        if not dry_run:
            dst.execute(
                """
                INSERT INTO tr3_import_runs (created_at, source_path, target_path, dry_run, overwrite, report_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (utcnow(), str(source), str(target), int(dry_run), int(overwrite), json.dumps(asdict(report), ensure_ascii=False)),
            )
            dst.commit()
    finally:
        dst.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importa lastfm_profiles do TR3 para TR4 com dry-run e backup.")
    parser.add_argument("--source", required=True, help="Banco SQLite antigo do TR3, ex.: ./app.db")
    parser.add_argument("--target", default=None, help="Banco SQLite atual do TR4. Default: DATABASE_URL ou data/app.db")
    parser.add_argument("--apply", action="store_true", help="Executa importação. Sem isso, roda dry-run.")
    parser.add_argument("--overwrite", action="store_true", help="Atualiza username existente quando diferente.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source).expanduser().resolve()
    target = resolve_sqlite_path(args.target)
    if source == target:
        print("ERRO: source e target são o mesmo arquivo. Não há o que importar; use outro target.", file=sys.stderr)
        return 2
    report = import_profiles(source, target, dry_run=not args.apply, overwrite=args.overwrite)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
