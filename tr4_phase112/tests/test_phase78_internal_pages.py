from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase78_internal_page_mode_and_native_back_button():
    assert "phase78-internal-pages" in ROUTER
    assert "tg.BackButton" in ROUTER
    assert "setTelegramBackButton(active)" in ROUTER
    assert "tgBackButton.onClick" in ROUTER


def test_phase78_detail_mode_hides_home_and_uses_page_header():
    assert "body.phase78-internal-pages.detail-mode #inicio_view" in ROUTER
    assert "position: sticky" in ROUTER
    assert "detail-title" in ROUTER
    assert "goBackToHomeList" in ROUTER


def test_phase78_keeps_minimal_nav_rows():
    assert "button.nav span:not(.nav-state)" in ROUTER
    assert "display: none !important" in ROUTER
