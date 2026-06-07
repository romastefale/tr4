
from pathlib import Path

HTML = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase74_uses_botfather_page_class():
    assert 'phase74-botfather-pages' in HTML
    assert 'detail-mode' in HTML
    assert 'id="detail_back"' in HTML


def test_phase74_hides_redundant_nav_subtitles_and_states():
    assert 'button.nav span:not(.nav-state) { display: none !important; }' in HTML
    assert '.nav-state { display: none !important; }' in HTML


def test_phase74_uses_neutral_dark_surfaces():
    assert 'background: #161b20' in HTML
    assert 'background: #1b222a' in HTML
    assert 'background: #242c36' in HTML


def test_phase74_keeps_js_regex_safe():
    assert 'split(/\\\\s+/)' in HTML or 'split(/\\s+/)' in HTML
    assert 'split(/\n+/)' not in HTML
