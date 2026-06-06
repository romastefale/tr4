from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / 'app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase65_removes_visible_ui_sujeira_and_internal_id_terms():
    assert 'iPhone' not in ROUTER
    assert 'canal operacional' not in ROUTER
    assert 'canal crítico' not in ROUTER
    assert 'ID real' not in ROUTER
    assert 'IDs continuam internos' not in ROUTER
    assert 'Título personalizado do admin' not in ROUTER
    assert 'Definir título admin' not in ROUTER
    assert 'membros, admins e bots' not in ROUTER


def test_phase65_standardizes_status_and_feedback_language():
    assert '.statusbar.ok' in ROUTER
    assert '.statusbar.warn' in ROUTER
    assert '.statusbar.bad' in ROUTER
    assert 'feedbackKindLabel' in ROUTER
    assert 'sucesso' in ROUTER
    assert 'atenção' in ROUTER
    assert 'erro' in ROUTER
    assert '[${entry.time}] ${feedbackKindLabel(entry.kind)}: ${entry.text}' in ROUTER


def test_phase65_keeps_group_card_compact_and_action_copy_clear():
    assert '#grupo_descricao' in ROUTER
    assert '-webkit-line-clamp: 2' in ROUTER
    assert 'Pronto. Ações liberadas conforme permissão do operador, alvo selecionado e direito real do bot.' in ROUTER
    assert 'Ação de tópico não aplicada.' in ROUTER
    assert 'Ação bloqueada por permissão real do bot ou do operador.' in ROUTER


def test_phase65_owner_config_uses_public_friendly_labels():
    assert 'Configuração do proprietário' in ROUTER
    assert 'Proprietários técnicos' in ROUTER
    assert 'Gerar bloco final' in ROUTER
    assert 'Bloco final para copiar' in ROUTER
    assert 'Copiar bloco final' in ROUTER
