from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase82_class_enabled():
    assert "phase82-state-feedback" in ROUTER


def test_phase82_compacts_empty_loading_and_feedback_states():
    assert "body.phase82-state-feedback .search-empty" in ROUTER
    assert "body.phase82-state-feedback .empty" in ROUTER
    assert "body.phase82-state-feedback .feedback-panel" in ROUTER
    assert "Carregando acesso…" in ROUTER
    assert "Nada encontrado para" in ROUTER


def test_phase82_does_not_hide_search_suggestions():
    assert "phase81-search-suggestions" in ROUTER
    assert "quick-suggestion" in ROUTER
    assert 'box.classList.toggle("hidden", !rows.length && query.length < 2)' in ROUTER
