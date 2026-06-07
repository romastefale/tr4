from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase81_class_enabled():
    assert "phase81-search-suggestions" in ROUTER


def test_empty_search_shows_group_suggestions_before_selection():
    assert 'if (q.length < 2)' in ROUTER
    assert 'palcosDisponiveis || []' in ROUTER
    assert 'quick: true' in ROUTER
    assert 'box.classList.toggle("hidden", !rows.length && query.length < 2)' in ROUTER


def test_search_results_keep_opening_group_and_window():
    assert 'if (row.palco) selectPalco(row.palco, null);' in ROUTER
    assert 'else if (row.view) openView(row.view);' in ROUTER
