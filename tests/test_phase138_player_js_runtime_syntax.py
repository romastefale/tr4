from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path


def _html_constants() -> dict[str, str]:
    tree = ast.parse(Path("app/equalizador/router.py").read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.endswith("_HTML"):
                result[target.id] = node.value.value
    return result


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S)


def test_phase138_evaluated_player_html_does_not_break_regex_literal():
    html = _html_constants()["_PUBLIC_MUSIC_HTML"]
    assert "replace(/\\n/g" in html
    assert "replace(/\n/g" not in html
    assert "replace(/\n" not in html


def test_phase138_embedded_html_scripts_pass_node_check(tmp_path):
    node = shutil.which("node")
    assert node, "node precisa existir para validar JavaScript embutido"
    for html_name, html in _html_constants().items():
        for index, script in enumerate(_scripts(html)):
            path = tmp_path / f"{html_name}_{index}.js"
            path.write_text(script, encoding="utf-8")
            completed = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert completed.returncode == 0, completed.stderr
