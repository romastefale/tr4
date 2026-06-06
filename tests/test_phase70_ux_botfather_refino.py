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


def test_phase70_uses_darker_telegram_like_palette_and_short_search():
    html = _html()
    assert "background: #17212b" in html
    assert "Buscar @, ID, grupo ou ação" in html
    assert "Pesquisar por @username, ID, grupo, janela ou ação" not in html
    assert "search-empty" in html
    assert "Sem resultados" in html


def test_phase70_removes_duplicate_group_name_element_and_long_intro_noise():
    html = _html()
    assert html.count('id="grupo_nome"') == 1
    assert "Revisões importantes:" not in html
    assert 'statusMesa("Pronto", "ok");' in html
    assert "Pronto. Ações liberadas conforme permissão" not in html


def test_phase70_preserves_regex_and_node_check_guardrails():
    html = _html()
    assert "split(/\\s+/).filter" in html
    assert "split(/\\n+/)" in html
    assert "split(/\n+/)" not in html.replace("split(/\\n+/)", "")
