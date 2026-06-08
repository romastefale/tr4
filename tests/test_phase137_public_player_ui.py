from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROUTER = Path("app/equalizador/router.py")


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def _html_block(name: str) -> str:
    text = _router_text()
    start_marker = f'{name} = """'
    start = text.index(start_marker) + len(start_marker)
    if name == "_PUBLIC_MUSIC_HTML":
        end = text.index('"""\n\n@router.get("/player"', start)
    else:
        end = text.index('"""\n\n\n@router.get("", response_class=HTMLResponse)', start)
    return text[start:end]


def _public_html() -> str:
    return _html_block("_PUBLIC_MUSIC_HTML")


def _public_script() -> str:
    html = _public_html()
    start = html.index("<script>", html.index("<body")) + len("<script>")
    end = html.rindex("</script>")
    return html[start:end]


def _equalizador_main_script() -> str:
    html = _html_block("_EQUALIZADOR_HTML")
    scripts: list[str] = []
    pos = 0
    while True:
        start = html.find("<script>", pos)
        if start == -1:
            break
        end = html.find("</script>", start)
        assert end != -1
        scripts.append(html[start + len("<script>"):end])
        pos = end + len("</script>")
    assert scripts
    return scripts[-1]


def _section(html: str, class_name: str) -> str:
    marker = f'class="{class_name}"'
    marker_at = html.index(marker)
    start = html.rfind("<section", 0, marker_at)
    end = html.index("</section>", marker_at) + len("</section>")
    return html[start:end]


def test_phase137_router_compiles() -> None:
    py_compile.compile(str(ROUTER), doraise=True)


def test_phase137_public_html_uses_clean_now_hero_first() -> None:
    html = _public_html()
    body_start = html.index("<body")
    first_section = html.index("<section", body_start)
    assert 'class="now-hero"' in html[first_section:first_section + 160]
    assert "now-hero__cover" in html
    assert "TOCANDO AGORA" in html
    assert "tigraoRADIO" in _section(html, "now-hero")
    assert "@tigraoRADIObot" not in html


def test_phase137_now_card_has_no_redundant_controls() -> None:
    hero = _section(_public_html(), "now-hero")
    forbidden = ["Atualizar", "Publicar atual", "selectedGroup", "publishPanel", "status", "Grupo para publicação"]
    for token in forbidden:
        assert token not in hero
    assert "Você · ♫" in hero


def test_phase137_command_matrix_is_3x3_compact_and_text_only() -> None:
    html = _public_html()
    grid_start = html.index('id="commandGrid"')
    grid_end = html.index("</div>", grid_start)
    grid = html[grid_start:grid_end]
    labels = re.findall(r'<button class="cmd(?: primary)?" type="button" data-command="[^"]+">([^<]+)</button>', grid)
    assert labels == ["Tocando", "Publicar", "Semana", "Mês", "Ranking", "Canvas", "Story", "Letra", "Mosaico"]
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in html
    assert "<small" not in grid
    assert grid.count('class="cmd') == 9


def test_phase137_panel_group_and_result_are_outside_music_card() -> None:
    html = _public_html()
    hero = _section(html, "now-hero")
    command_area = _section(html, "command-area")
    assert 'id="modBtn"' in command_area
    assert html.index('id="modBtn"') > html.index('id="commandGrid"')
    assert html.index('id="publishPanel"') > html.index('id="commandGrid"')
    assert html.index('id="status"') > html.index('id="publishPanel"')
    assert 'id="publishPanel"' not in hero
    assert 'id="status"' not in hero


def test_phase137_public_commands_are_internal_and_include_existing_bot_commands() -> None:
    text = _router_text()
    script = _public_script()
    assert "?start=cmd_" not in script
    assert "cmd_" not in script
    assert "/equalizador/api/public/command/" in script
    assert "runPublicCommand" in script
    for command in ("tcanvas", "tstory", "tly", "tnow"):
        assert f'command == "{command}"' in text or f'"{command}"' in script
    assert "lyrics_service.get_snippet" in text


def test_phase137_apiheaders_not_redeclared_in_equalizador_script() -> None:
    script = _equalizador_main_script()
    assert script.count("let apiHeaders") == 1
    assert "let publicApiHeaders" in script


def test_phase137_embedded_javascript_passes_node_check(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node não disponível neste ambiente")
    public_js = tmp_path / "public_player.js"
    equalizador_js = tmp_path / "equalizador.js"
    public_js.write_text(_public_script(), encoding="utf-8")
    equalizador_js.write_text(_equalizador_main_script(), encoding="utf-8")
    subprocess.run([node, "--check", str(public_js)], check=True)
    subprocess.run([node, "--check", str(equalizador_js)], check=True)
