#!/usr/bin/env python3
"""Verificação final de importação TR3 -> TR4.

Não escreve no banco. Compara contagens das tabelas legadas seguras entre o
banco recuperado e o banco persistente de produção. Retorna JSON próprio para
log/auditoria sem expor tokens, linhas ou payloads sensíveis.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from scripts.import_tr3_legacy_tables import SAFE_TABLES, quote_ident, resolve_sqlite_path, table_exists


def _count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])


def compare(source: Path, target: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "source_exists": source.exists(),
        "target_exists": target.exists(),
        "same_file": source == target,
        "tables": {},
        "ok": False,
        "missing_or_lower": [],
        "next_step": "Verifique os caminhos dos bancos.",
    }
    if not source.exists() or not target.exists():
        return result
    if source == target:
        result["ok"] = True
        result["next_step"] = "Banco recuperado e banco alvo são o mesmo arquivo; não importe sobre ele mesmo."
        return result
    missing: list[str] = []
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
        for table in SAFE_TABLES:
            source_count = _count(src, table)
            target_count = _count(dst, table)
            status = "ok"
            if source_count is not None and (target_count is None or target_count < source_count):
                status = "importar_ou_completar"
                missing.append(table)
            result["tables"][table] = {
                "source": source_count,
                "target": target_count,
                "status": status,
            }
    result["missing_or_lower"] = missing
    result["ok"] = not missing
    result["next_step"] = "Importação conferida." if not missing else "Rode import_tr3_legacy_tables.py com --apply após backup."
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Confere se o legado TR3 foi importado para o banco persistente.")
    parser.add_argument("--source", required=True, help="Banco TR3 recuperado.")
    parser.add_argument("--target", default=None, help="Banco TR4 alvo. Padrão: DATABASE_URL ou /data/app.db.")
    parser.add_argument("--strict", action="store_true", help="Retorna 1 quando ainda houver tabela a importar.")
    args = parser.parse_args()
    report = compare(Path(args.source).expanduser().resolve(), resolve_sqlite_path(args.target))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
