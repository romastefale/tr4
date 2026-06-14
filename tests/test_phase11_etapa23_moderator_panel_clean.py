from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text()


def test_moderator_panel_has_three_visible_tabs_declared():
    assert 'data-moderator-tab="1"><strong>Mensagens</strong>' in ROUTER
    assert 'data-moderator-tab="1"><strong>Pessoas</strong>' in ROUTER
    assert 'data-moderator-tab="1"><strong>Música</strong>' in ROUTER
    assert 'button.nav:not([data-moderator-tab="1"])' in ROUTER


def test_owner_center_is_not_loaded_by_panel_bootstrap():
    assert 'const loadOwnerPanels = false;' in ROUTER
    assert 'Configurações owner ficam no /tctl (/show legado)' in ROUTER
    assert 'loadOwnerPanels ? api(base + "/ddx")' in ROUTER
    assert 'loadOwnerPanels ? api(base + "/radio/rascunhos")' in ROUTER


def test_music_tab_only_exposes_current_music_panel():
    assert 'moderator-music-panel' in ROUTER
    assert 'Enviar música atual' in ROUTER
    assert 'Catálogo, agendamento e bloqueios ficam no /tctl (/show legado)' in ROUTER


def test_open_view_refuses_owner_center_views():
    assert 'if (!moderatorPanelViews.has(id))' in ROUTER
    assert 'Esta configuração fica no /tctl (/show legado)' in ROUTER
