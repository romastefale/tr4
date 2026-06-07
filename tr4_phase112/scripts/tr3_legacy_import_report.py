#!/usr/bin/env python3
"""Relatório seguro do legado TR3 e do banco TR4 persistente.

Não escreve dados. Serve para confirmar se o banco recuperado já está no volume
ou se deve ser importado por scripts/import_tr3_legacy_tables.py.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from scripts.import_tr3_legacy_tables import SAFE_TABLES, resolve_sqlite_path, table_exists, quote_ident


def counts(path: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    if not path.exists():
        return {table: None for table in SAFE_TABLES}
    with sqlite3.connect(str(path)) as conn:
        for table in SAFE_TABLES:
            if not table_exists(conn, table):
                out[table] = None
                continue
            out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Mostra contagens do banco TR3 recuperado e do banco TR4 alvo.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", default=None)
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    target = resolve_sqlite_path(args.target)
    report = {
        "source": str(source),
        "target": str(target),
        "same_file": source == target,
        "source_exists": source.exists(),
        "target_exists": target.exists(),
        "source_counts": counts(source),
        "target_counts": counts(target),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
