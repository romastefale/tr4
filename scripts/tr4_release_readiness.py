#!/usr/bin/env python3
"""Static release readiness checks for the TR4 Mini App finalization block.

This script intentionally avoids secrets, network access, and database writes. It
checks only code-level invariants that previously caused production regressions.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app" / "equalizador" / "router.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "app" / "config" / "settings.py").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"ERRO: {message}")


def main() -> None:
    import_block = ROUTER.split("from app.equalizador.rbac_runtime import (", 1)[1].split(")", 1)[0]
    require("governance_persistence_public" in import_block, "governance_persistence_public não importado no router")
    require('@router.get("/api/configuracao")' in ROUTER, "rota /api/configuracao ausente")
    require('"governanca_persistencia": governance_persistence_public(' in ROUTER, "configuração sem resumo de governança")
    require('@router.get("/player", response_class=HTMLResponse)' in ROUTER, "rota pública /equalizador/player ausente")
    require('@router.get("/api/public/status")' in ROUTER, "status público do player ausente")
    require('"musica_publica_sem_curtidas"' in ROUTER, "layout público sem curtidas não marcado")
    require('TR4_MUSIC_REACTIONS_ENABLED = _bool_env("TR4_MUSIC_REACTIONS_ENABLED", False' in SETTINGS, "LED/reactions não estão desligados por padrão")
    print("TR4 release readiness: OK")


if __name__ == "__main__":
    main()
