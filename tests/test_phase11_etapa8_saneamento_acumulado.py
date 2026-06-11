from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
PERSISTENCIA = (ROOT / "app/equalizador/persistencia.py").read_text(encoding="utf-8")


def test_convites_revogar_returns_revocation_result_without_fallthrough_to_export() -> None:
    start = ROUTER.index('if acao == "revogar":')
    end = ROUTER.index('result = await exportar_link_primario(', start)
    revogar_block = ROUTER[start:end]
    assert 'result = await revogar_convite(' in revogar_block
    assert 'return result' in revogar_block
    assert 'exportar_link_primario' not in revogar_block


def test_backend_confirmation_guard_exists_and_frontend_sends_confirmation() -> None:
    assert '_BACKEND_CONFIRMATION_ACTIONS = {' in ROUTER
    assert 'confirmacao_obrigatoria' in ROUTER
    assert '_require_backend_confirmation(ajuste, payload)' in ROUTER
    assert '_require_backend_confirmation("mensagens.apagar_lote", payload)' in ROUTER
    assert '_require_backend_confirmation(action_code, payload)' in ROUTER
    assert 'payload.confirmacao = "CONFIRMAR AJUSTE"' in ROUTER
    assert 'msg_refs: refs, confirmacao: "CONFIRMAR AJUSTE"' in ROUTER


def test_governante_gate_covers_legacy_action_families() -> None:
    assert '_require_governante_scope_for_action(identity, palco_id=int(palco["telegram_chat_id"]), action=canal)' in ROUTER
    assert 'action="reacoes.reactor.silenciar"' in ROUTER
    assert '_require_owner_only_module(identity, module="radio")' in ROUTER
    assert ROUTER.count('_require_owner_only_module(identity, module="radio")') >= 10
    assert '"radio_view", "novos_view"' in ROUTER


def test_reaction_audit_removed_from_runtime_app_release_surface() -> None:
    assert 'reaction_audit' not in ROUTER
    assert 'reaction_audit' not in PERSISTENCIA


def test_release_check_non_strict_has_no_errors_after_saneamento() -> None:
    env = os.environ.copy()
    env.pop('TR3_TELEGRAM_BOT_TOKEN', None)
    env.pop('TELEGRAM_BOT_TOKEN', None)
    env.pop('TR3_BASE_URL', None)
    env.pop('BASE_URL', None)
    res = subprocess.run(
        [sys.executable, 'scripts/equalizador_release_check.py'],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert '[ERRO]' not in res.stdout
