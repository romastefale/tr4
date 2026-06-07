import ast
from pathlib import Path


def _rendered_equalizador_html() -> str:
    source = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_EQUALIZADOR_HTML":
                    return ast.literal_eval(node.value)
    raise AssertionError("_EQUALIZADOR_HTML não encontrado")


def test_phase67_alias_split_regex_survives_python_string_rendering():
    html = _rendered_equalizador_html()
    assert "value.split(/\\n+/).forEach" in html
    assert "value.split(/\n+/).forEach" not in html
