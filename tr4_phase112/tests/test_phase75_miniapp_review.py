from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase75_class_is_enabled():
    assert 'phase75-miniapp-review' in ROUTER
    assert 'phase75-miniapp-review' in ROUTER and 'phase76-governance-compact' in ROUTER


def test_phase75_keeps_nav_labels_minimal():
    assert 'body.phase75-miniapp-review button.nav span:not(.nav-state),' in ROUTER
    assert 'display: none !important;' in ROUTER
    assert "content: '›'" in ROUTER


def test_phase75_button_grid_prevents_half_width_single_buttons():
    assert 'body.phase75-miniapp-review .toolbar > button:only-child' in ROUTER
    assert 'grid-column: 1 / -1' in ROUTER
    assert 'body.phase75-miniapp-review .toolbar > button:nth-child(odd):last-child' in ROUTER


def test_phase75_neutral_surfaces_not_blue_base():
    assert 'background: #11161c' in ROUTER
    assert 'background: #171d23' in ROUTER
    assert 'background: #232a32' in ROUTER


def test_phase75_preserves_js_regex_escaping():
    assert 'join("\\\\n")' in ROUTER or 'join("\\\\n"' in ROUTER
