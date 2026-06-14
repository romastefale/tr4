from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/equalizador/router.py"


def _router() -> str:
    return ROUTER.read_text(encoding="utf-8")


def test_equalizador_root_is_player_only_after_contextual_fsm() -> None:
    source = _router()
    assert "_EQUALIZADOR_DENIED_HTML" in source
    assert "data-equalizador-denied-shell" in source
    assert "Web App é player musical" in source
    assert "return _equalizador_html_response(_PUBLIC_MUSIC_HTML)" in source
    assert "Moderação e governança ficam no FSM privado/X9" in source


def test_public_panel_navigation_sets_cookie_before_get_equalizador() -> None:
    source = _router()
    assert 'const PANEL_COOKIE_KEY="tr4_equalizador_eqs"' in source
    assert "document.cookie=PANEL_COOKIE_KEY" in source
    assert "Path=/equalizador" in source
    assert "SameSite=Lax" in source


def test_destructive_actions_require_inline_confirmation_without_owner_lock() -> None:
    source = _router()
    assert "const destructiveActions = new Set" in source
    for action in [
        "mensagens.enviar",
        "mensagens.apagar",
        "membros.remover",
        "convites.revogar",
        "entradas.recusar",
        "reacoes.mensagem.limpar",
        "reacoes.recentes.limpar",
        "canais_remetentes.banir",
    ]:
        assert f'"{action}"' in source
    assert "const requiresInlineConfirmation = (action) => criticalActions.has(action) || destructiveActions.has(action);" in source
    assert "armInlineConfirmation(button, actionLabels[action] || action, requiresInlineConfirmation(action), previewForAction(action, payload))" in source
    assert "const previewForAction = (action, payload) =>" in source
    # Destructive actions must not be added to criticalActions, because that would
    # incorrectly make normal governante actions owner-only.
    critical_line = next(line for line in source.splitlines() if "const criticalActions = new Set" in line)
    assert "mensagens.apagar" not in critical_line
    assert "membros.remover" not in critical_line
