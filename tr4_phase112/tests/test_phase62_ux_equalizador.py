from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase62_feedback_panel_and_inline_confirmation_present():
    assert 'feedback_panel' in ROUTER
    assert 'Confirmações e erros desta sessão' in ROUTER
    assert 'armInlineConfirmation' in ROUTER
    assert 'Toque novamente no mesmo botão para confirmar' in ROUTER
    assert 'navigator.clipboard.writeText(texto)' in ROUTER


def test_phase62_member_preview_and_selection_feedback_present():
    assert 'mesa_pessoas_resumo' in ROUTER
    assert 'mesa_membros_preview' in ROUTER
    assert 'renderMesaMembrosResumo' in ROUTER
    assert '.bulk-item.selected' in ROUTER
    assert 'haptic("selection")' in ROUTER


def test_phase62_no_browser_confirm_in_critical_equalizador_actions():
    # A UX da fase 62 usa confirmação inline persistente no painel em vez de popup nativo.
    assert 'confirm(' not in ROUTER
