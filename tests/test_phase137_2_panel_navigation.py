from __future__ import annotations

import py_compile
import shutil
import subprocess
from pathlib import Path

import pytest

ROUTER = Path("app/equalizador/router.py")


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def _html_block() -> str:
    text = _router_text()
    start = text.index('_PUBLIC_MUSIC_HTML = """') + len('_PUBLIC_MUSIC_HTML = """')
    end = text.index('"""\n\n@router.get("/player"', start)
    return text[start:end]


def _public_script() -> str:
    html = _html_block()
    start = html.index("<script>") + len("<script>")
    end = html.rindex("</script>")
    return html[start:end]


def _equalizador_script() -> str:
    text = _router_text()
    marker = '_EQUALIZADOR_HTML = """'
    html_start = text.index(marker) + len(marker)
    public_marker = text.index('_PUBLIC_MUSIC_HTML = """', html_start)
    html_end = text.rfind('"""', html_start, public_marker)
    html = text[html_start:html_end]
    start = html.rindex("<script>") + len("<script>")
    end = html.rindex("</script>")
    return html[start:end]


def test_phase137_2_sources_compile() -> None:
    py_compile.compile(str(ROUTER), doraise=True)


def test_phase137_2_public_panel_button_preserves_session_and_navigates() -> None:
    html = _html_block()
    script = _public_script()
    assert 'id="modBtn"' in html
    assert 'href="/equalizador"' in html
    assert 'const PANEL_SESSION_KEY="tr4_equalizador_eqs"' in script
    assert 'function sessionToken(value)' in script
    assert 'value.token?String(value.token):""' in script
    assert 'window.sessionStorage.setItem(PANEL_SESSION_KEY,token)' in script
    assert 'function openPanel()' in script
    assert 'new URL("/equalizador",window.location.href)' in script
    assert 'window.location.assign(url.toString())' in script
    assert 'modBtn.addEventListener("click"' in script


def test_phase137_2_equalizador_accepts_session_created_by_public_player() -> None:
    script = _equalizador_script()
    assert 'localStorage.getItem("tr4_public_eqs")' in script
    assert 'sessionStorage.getItem(SESSION_KEY) || localStorage.getItem("tr4_public_eqs")' in script


def test_phase137_2_public_and_panel_javascript_pass_node_check(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node não disponível neste ambiente")
    public_js = tmp_path / "phase137_2_public_player.js"
    panel_js = tmp_path / "phase137_2_equalizador.js"
    public_js.write_text(_public_script(), encoding="utf-8")
    panel_js.write_text(_equalizador_script(), encoding="utf-8")
    subprocess.run([node, "--check", str(public_js)], check=True)
    subprocess.run([node, "--check", str(panel_js)], check=True)
