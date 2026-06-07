from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "bulk route",
        "app/equalizador/router.py",
        '@router.post("/api/palcos/{grp_ref}/mensagens/apagar-lote")',
    ),
    (
        "bulk frontend endpoint",
        "app/equalizador/router.py",
        '"mensagens.apagar_lote": "mensagens/apagar-lote"',
    ),
    (
        "bulk safe payload",
        "app/equalizador/router.py",
        "JSON.stringify({ msg_refs: refs })",
    ),
    (
        "bulk Bot API method",
        "app/equalizador/mesa.py",
        'telegram_api_call(bot_token, "deleteMessages", telegram_payload)',
    ),
    (
        "bulk ref cap",
        "app/equalizador/mesa.py",
        "Selecione no máximo 100 mensagens por lote.",
    ),
    (
        "ddx durable worker",
        "app/equalizador/ddx.py",
        "process_due_ddx_soft_deletions",
    ),
    (
        "ddx startup task",
        "app/main.py",
        "_ddx_scheduler_task = asyncio.create_task(_ddx_scheduler_loop())",
    ),
    (
        "telegram structured error payload",
        "app/equalizador/router.py",
        "telegram_error_payload(info)",
    ),
    (
        "service shutdown coverage",
        "app/bot/telegram.py",
        '("lastfm_capsule", lastfm_capsule_service.shutdown)',
    ),
)


def main() -> int:
    failures: list[str] = []
    for label, rel_path, needle in CHECKS:
        path = ROOT / rel_path
        if not path.exists():
            failures.append(f"{label}: arquivo ausente: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        if needle not in text:
            failures.append(f"{label}: trecho obrigatório ausente em {rel_path}")
    if failures:
        for failure in failures:
            print(f"[FALHA] {failure}")
        return 1
    print("Fase 60: auditoria estática essencial aprovada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
