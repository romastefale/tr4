from pathlib import Path

MULTI = Path("app/equalizador/multimidia.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase97_uses_publishing_state_before_telegram_call():
    assert "status='publishing'" in MULTI
    assert "WHERE session_ref=:ref AND status='ready'" in MULTI
    assert "Sessão já está publicando" in MULTI


def test_phase97_failed_state_is_persisted_with_public_error():
    assert "status='failed'" in MULTI
    assert "error_public=:error" in MULTI
    assert "Publicação multimídia não concluída" in MULTI


def test_phase97_webapp_disables_publish_until_ready_and_handles_conflict():
    assert 'publicar.disabled = row.status !== "ready"' in ROUTER
    assert "Sessão em conflito. Atualizei a lista" in ROUTER
