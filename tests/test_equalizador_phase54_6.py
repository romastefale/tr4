from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase54_6_diagnostic_window_crosses_operator_and_bot_layers() -> None:
    source = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="diagnostico_resumo"' in source
    assert 'id="diagnostico_operador"' in source
    assert 'id="diagnostico_bot"' in source
    assert 'id="diagnostico_acoes"' in source
    assert 'function renderDiagnosticoPermissoes()' in source
    assert 'const diagnosticForAction = (codigo) =>' in source
    assert 'canal do operador ausente' in source
    assert 'direito real do bot indisponível' in source
    assert 'ação crítica restrita ao administrador principal' in source


def test_phase54_6_ui_aliases_actions_to_effective_permission_channels() -> None:
    source = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert '"convites.exportar_primario": "convites.criar"' in source
    assert '"reacoes.mensagem.limpar": "reacoes.limpar"' in source
    assert 'const effectiveCanal = (codigo) =>' in source
    assert 'const botCanRun = (codigo) =>' in source


def test_phase54_6_message_send_participates_in_bot_rights_diagnostic() -> None:
    afinacao = (ROOT / "app/equalizador/afinacao.py").read_text(encoding="utf-8")
    assert '"codigo": "mensagens.enviar"' in afinacao
    assert '"nome": "Enviar mensagens"' in afinacao
    assert '"direitos": ()' in afinacao
