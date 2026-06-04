from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "app/main.py",
    "app/bootstrap.py",
    "app/equalizador/router.py",
    "app/equalizador/security.py",
    "app/equalizador/identity.py",
    "app/equalizador/permissions.py",
    "app/equalizador/palcos.py",
    "app/equalizador/afinacao.py",
    "app/equalizador/mesa.py",
    "app/equalizador/maestro.py",
    "app/equalizador/hardening.py",
    "docs/EQUALIZADOR_RELEASE_OPERACIONAL.md",
]

FORBIDDEN_APP_PATTERNS = [
    re.compile(r"reaction_audit", re.IGNORECASE),
    re.compile(r"new_member_watch", re.IGNORECASE),
    re.compile(r"TR3_SECURITY_", re.IGNORECASE),
    re.compile(r"TR3_AUDIT_", re.IGNORECASE),
    re.compile(r"TR3_PANIC_", re.IGNORECASE),
    re.compile(r"/hidden\b", re.IGNORECASE),
    re.compile(r"/debuguser\b", re.IGNORECASE),
    re.compile(r"/kingplay\b", re.IGNORECASE),
]

def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _status(kind: str, message: str) -> str:
    return f"[{kind}] {message}"


def check_required_files() -> list[str]:
    issues: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            issues.append(_status("ERRO", f"arquivo obrigatório ausente: {rel}"))
    return issues


def check_removed_residue() -> list[str]:
    issues: list[str] = []
    scan_roots = [ROOT / "app"]
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in FORBIDDEN_APP_PATTERNS:
                if pattern.search(text):
                    issues.append(_status("ERRO", f"resíduo antigo encontrado em {path.relative_to(ROOT)}: {pattern.pattern}"))
    return issues


def check_router_public_surface() -> list[str]:
    issues: list[str] = []
    router_path = ROOT / "app/equalizador/router.py"
    if not router_path.exists():
        return [_status("ERRO", "router do Equalizador ausente")]
    text = router_path.read_text(encoding="utf-8", errors="ignore")
    if "include_in_schema=False" not in text:
        issues.append(_status("ERRO", "router do Equalizador deve ficar fora do OpenAPI público"))
    if "Authorization" not in text or "tma" not in text or "eqs" not in text:
        issues.append(_status("ERRO", "router não evidencia autenticação tma/eqs"))
    return issues


def check_runtime_env(strict: bool) -> list[str]:
    issues: list[str] = []
    warnings: list[str] = []

    token = os.getenv("TR3_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = (os.getenv("TR3_BASE_URL") or os.getenv("BASE_URL") or "").strip()
    database_url = (os.getenv("TR3_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    equalizador_enabled = _bool_env("TR4_EQUALIZADOR_ENABLED", False)

    if not token:
        warnings.append(_status("AVISO", "TR3_TELEGRAM_BOT_TOKEN/TELEGRAM_BOT_TOKEN não definido neste ambiente"))
    if not base_url or base_url == "http://localhost:8000":
        warnings.append(_status("AVISO", "TR3_BASE_URL/BASE_URL não aponta para domínio público"))
    elif not base_url.startswith("https://"):
        warnings.append(_status("AVISO", "TR3_BASE_URL/BASE_URL deve usar HTTPS para Mini App/webhook"))
    if database_url and not database_url.lower().startswith("sqlite:"):
        issues.append(_status("ERRO", "TR3_DATABASE_URL/DATABASE_URL deve ser SQLite neste build"))

    if equalizador_enabled:
        required_when_on = [
            "TR4_EQUALIZADOR_APP_NAME",
            "TR4_EQUALIZADOR_MAESTRO_IDS",
            "TR4_EQUALIZADOR_OPERADOR_IDS",
            "TR4_EQUALIZADOR_PALCO_IDS",
            "TR4_EQUALIZADOR_CANAIS",
        ]
        for name in required_when_on:
            if not os.getenv(name, "").strip():
                issues.append(_status("ERRO", f"{name} é obrigatório quando TR4_EQUALIZADOR_ENABLED=true"))
        if not _bool_env("TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS", True):
            issues.append(_status("ERRO", "TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS deve permanecer true"))

    if strict:
        issues.extend(warnings)
    else:
        issues.extend(warnings)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica pré-release do TR4 Equalizador sem imprimir segredos.")
    parser.add_argument("--strict", action="store_true", help="retorna erro se houver aviso de ambiente incompleto")
    args = parser.parse_args()

    checks = []
    checks.extend(check_required_files())
    checks.extend(check_removed_residue())
    checks.extend(check_router_public_surface())
    checks.extend(check_runtime_env(strict=args.strict))

    errors = [line for line in checks if line.startswith("[ERRO]")]
    warnings = [line for line in checks if line.startswith("[AVISO]")]

    if checks:
        for line in checks:
            print(line)
    else:
        print("[OK] release operacional validado")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
