from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / 'app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase66_has_visible_refresh_state_and_manual_refresh_button():
    assert 'id="mesa_refresh"' in ROUTER
    assert 'id="refresh_state"' in ROUTER
    assert 'setRefreshState("Atualizando dados do grupo e janelas do painel…", "loading")' in ROUTER
    assert 'Atualizado agora · ${elapsed}s · janela atual: ${viewTitle(currentViewId)}' in ROUTER


def test_phase66_adds_loading_animation_without_native_popup():
    assert '@keyframes spin' in ROUTER
    assert '@keyframes shimmer' in ROUTER
    assert '.skeleton-line' in ROUTER
    assert 'setListLoading("mensagens_lote_lista", "Carregando mensagens recentes…")' in ROUTER
    assert 'setListLoading("mesa_membros_preview", "Carregando pessoas do painel…")' in ROUTER


def test_phase66_button_working_state_is_reversible_and_accessible():
    assert 'aria-busy' in ROUTER
    assert 'dataset.workingLock' in ROUTER
    assert 'dataset.wasDisabled' in ROUTER
    assert 'button.disabled = button.dataset.wasDisabled === "1"' in ROUTER
    assert 'button.classList.toggle("loading", state === "loading")' in ROUTER


def test_phase66_refresh_is_tied_to_action_completion():
    assert 'Sincronizando painel após a ação…' in ROUTER
    assert 'Atualizando lista de mensagens após apagamento…' in ROUTER
    assert 'Sincronizando rascunhos e histórico de rádio…' in ROUTER
    assert 'Sincronizando perfil do grupo após foto…' in ROUTER
