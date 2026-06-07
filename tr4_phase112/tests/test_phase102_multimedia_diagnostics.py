from pathlib import Path

MULTI = Path("app/equalizador/multimidia.py").read_text(encoding="utf-8")
TELEGRAM = Path("app/bot/telegram.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase102_public_session_has_diagnostic_fields():
    assert '"pode_publicar"' in MULTI
    assert '"codigo_estado"' in MULTI
    assert '"proximo_passo"' in MULTI
    assert 'Sessão ainda aguardando conteúdo' in MULTI


def test_phase102_deeplink_does_not_reset_ready_session():
    assert 'Reabrir o deep link não pode apagar uma mídia já recebida' in MULTI
    assert 'if current_status == "ready"' in MULTI


def test_phase102_private_plain_text_can_fill_active_session_without_consuming_all_text():
    assert 'active_session_for_user' in TELEGRAM
    assert 'return UNHANDLED' in TELEGRAM
    assert 'equalizador_multimedia_private_text_active_session' in TELEGRAM


def test_phase102_route_returns_structured_conflict_state():
    assert '"estado": (sessao_publica or {}).get("status")' in ROUTER
    assert '"proximo_passo": (sessao_publica or {}).get("proximo_passo")' in ROUTER
