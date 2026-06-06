from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_phase60_bulk_delete_uses_safe_refs_and_single_bot_api_method() -> None:
    router = read("app/equalizador/router.py")
    mesa = read("app/equalizador/mesa.py")
    assert '@router.post("/api/palcos/{grp_ref}/mensagens/apagar-lote")' in router
    assert 'JSON.stringify({ msg_refs: refs })' in router
    assert '"mensagens.apagar_lote": "mensagens.apagar"' in router
    assert '"message_ids": message_ids' in mesa
    assert 'telegram_api_call(bot_token, "deleteMessages", telegram_payload)' in mesa
    assert "Selecione no máximo 100 mensagens por lote." in mesa


def test_phase60_ddx_durable_worker_is_wired_without_new_table() -> None:
    main = read("app/main.py")
    ddx = read("app/equalizador/ddx.py")
    assert "process_due_ddx_soft_deletions" in main
    assert "_ddx_scheduler_loop" in main
    assert "eq_ddx_soft_pending" in ddx
    assert "scheduled_deletions" not in ddx


def test_phase60_telegram_error_payload_is_structured_and_sanitized() -> None:
    errors = read("app/equalizador/erros_telegram.py")
    router = read("app/equalizador/router.py")
    assert "bot_lacks_permissions" in errors
    assert "target_not_admin" in errors
    assert "target_already_admin" in errors
    assert "target_is_creator" in errors
    assert "telegram_error_payload(info)" in router
