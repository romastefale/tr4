from pathlib import Path


def test_custom_package_sanitizes_actions_and_blocks_forbidden():
    from app.equalizador.governante_webapp import (
        CUSTOM_ALLOWED_ACTIONS,
        CUSTOM_PACKAGE,
        sanitize_custom_actions,
    )

    assert CUSTOM_PACKAGE == "personalizado"
    assert "mensagens.enviar" in CUSTOM_ALLOWED_ACTIONS
    assert "mensagens.apagar_lote" not in CUSTOM_ALLOWED_ACTIONS
    assert "ddx.configurar" not in CUSTOM_ALLOWED_ACTIONS

    actions = sanitize_custom_actions([
        "mensagens.enviar",
        "mensagens.enviar",
        "membros.silenciar",
        "ddx.configurar",
        "kick",
        "radio.broadcast",
    ])
    assert actions == ("mensagens.enviar", "membros.silenciar")


def test_governante_scope_uses_actions_json_for_custom_package():
    source = Path("app/equalizador/governante_scope.py").read_text(encoding="utf-8")

    assert "CUSTOM_PACKAGE" in source
    assert "actions: object = None" in source
    assert "sanitize_custom_actions(actions)" in source
    assert "SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json" in source
    assert "action_value not in assignment.actions" in source
    assert "custom_allowed_actions" in source


def test_router_accepts_custom_actions_payload_and_shows_limit_status():
    source = Path("app/equalizador/router.py").read_text(encoding="utf-8")

    assert "actions=payload.get(\"actions\")" in source
    assert 'id="governante_scope_status"' in source
    assert "let governanteScopeRowsPorPalco = new Map();" in source
    assert "const renderGovernanteScopeStatus = () =>" in source
    assert "daily_remaining" in source
    assert "ownerOnlyViews.has(id)" in source
