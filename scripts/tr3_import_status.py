#!/usr/bin/env python3
"""Status seguro da importação TR3 -> TR4.

Não escreve no banco. Usa os caminhos padrão do fluxo recuperado:
- source: ~/tr4/app.db, salvo do volume antigo/recuperado
- target: banco persistente atual, por padrão /data/app.db quando existir

Retorna JSON com veredito simples para deploy/Termux.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.tr3_import_finalize_check import compare
from scripts.import_tr3_legacy_tables import resolve_sqlite_path


def _default_source() -> Path:
    return Path.home() / "tr4" / "app.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="Confere status da importação legada TR3 sem gravar dados.")
    parser.add_argument("--source", default=str(_default_source()), help="Banco TR3 recuperado. Padrão: ~/tr4/app.db")
    parser.add_argument("--target", default=None, help="Banco TR4 alvo. Padrão: DATABASE_URL ou /data/app.db")
    parser.add_argument("--strict", action="store_true", help="Retorna código 1 quando ainda faltar importar dados.")
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    target = resolve_sqlite_path(args.target)
    report = compare(source, target)
    missing = report.get("missing_or_lower") or []
    verdict = "importado" if report.get("ok") else "pendente"
    if report.get("same_file"):
        verdict = "mesmo_banco"
    output = {
        "ok": bool(report.get("ok")),
        "veredito": verdict,
        "source_exists": bool(report.get("source_exists")),
        "target_exists": bool(report.get("target_exists")),
        "same_file": bool(report.get("same_file")),
        "faltando_ou_menor": missing,
        "proximo_passo": report.get("next_step"),
        "tables": report.get("tables"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if args.strict and not output["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
