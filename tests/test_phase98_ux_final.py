from pathlib import Path
ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')

def test_phase98_class_and_neutral_surfaces():
    assert 'phase98-ux-final' in ROUTER
    assert '--eq-bg: #0e1217' in ROUTER
    assert 'body.phase98-ux-final .section-note' in ROUTER

def test_phase98_buttons_and_panels_compact():
    assert 'body.phase98-ux-final button.action' in ROUTER
    assert 'body.phase98-ux-final .panel { padding: 10px' in ROUTER
    assert 'body.phase98-ux-final .view .panel .panel' in ROUTER
