import ast
from pathlib import Path


def _html() -> str:
    source = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_EQUALIZADOR_HTML":
                    return ast.literal_eval(node.value)
    raise AssertionError("_EQUALIZADOR_HTML não encontrado")


def test_phase68_has_minimal_dark_shell_and_global_search():
    html = _html()
    assert 'body class="phase68-minimal"' in html
    assert 'id="global_search"' in html
    assert 'Buscar grupo, @, ID ou ação' in html
    assert 'search-result' in html


def test_phase68_windows_are_closed_by_default_and_group_picker_is_separate():
    html = _html()
    assert '<section id="mesa_view" class="view hidden">' in html
    assert 'closeAllViews();\n        await loadPalcoData();' in html
    assert 'openView("mesa_view");\n        await loadPalcoData();' not in html
    assert 'group-picker header-select' in html


def test_phase68_preserves_rendered_regex_safety():
    html = _html()
    assert 'value.split(/\\n+/).forEach' in html
    assert 'value.split(/\n+/).forEach' not in html
    assert 'split(/\\s+/).filter' in html
