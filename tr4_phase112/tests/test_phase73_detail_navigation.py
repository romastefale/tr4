
from pathlib import Path

HTML = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase73_detail_navigation_shell_exists():
    assert 'id="detail_nav"' in HTML
    assert 'id="detail_back"' in HTML
    assert 'detail-mode' in HTML
    assert 'setDetailMode' in HTML


def test_phase73_views_are_opened_as_internal_pages():
    assert 'document.body.classList.toggle("detail-mode", active)' in HTML
    assert 'detailNav.scrollIntoView' in HTML
    assert 'closeAllViews();' in HTML


def test_phase73_keeps_js_regex_escaped():
    assert 'split(/\\\\s+/)' in HTML or 'split(/\\s+/)' in HTML
    assert 'split(/\n+/)' not in HTML
