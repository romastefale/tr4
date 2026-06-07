from pathlib import Path
ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')

def test_phase99_class_and_styles():
    assert 'phase99-collapsible-menus' in ROUTER
    assert 'collapsible-list-shell' in ROUTER
    assert 'max-height: min(54vh, 420px)' in ROUTER

def test_phase99_filllist_collapses_long_known_lists():
    assert 'const collapsibleListIds = new Set' in ROUTER
    assert 'data.length > 3 && collapsibleListIds.has(id)' in ROUTER
    assert 'makeCollapsibleList(id, rendered, emptyText)' in ROUTER

def test_phase99_known_large_lists_covered():
    for name in ['config_operadores', 'seguranca_auditoria', 'historico', 'mensagens_lote_lista', 'mesa_membros_preview']:
        assert name in ROUTER
