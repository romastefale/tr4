from __future__ import annotations

import py_compile
import shutil
import subprocess
from pathlib import Path

import pytest

ROUTER = Path("app/equalizador/router.py")


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def _equalizador_html() -> str:
    text = _router_text()
    marker = '_EQUALIZADOR_HTML = """'
    html_start = text.index(marker) + len(marker)
    public_marker = text.index('_PUBLIC_MUSIC_HTML = """', html_start)
    html_end = text.rfind('"""', html_start, public_marker)
    return text[html_start:html_end]


def _equalizador_script() -> str:
    html = _equalizador_html()
    start = html.rindex("<script>") + len("<script>")
    end = html.rindex("</script>")
    return html[start:end]


def test_phase137_4_panel_source_compiles() -> None:
    py_compile.compile(str(ROUTER), doraise=True)


def test_phase137_4_panel_telegram_script_is_non_blocking_and_reports_bootstrap() -> None:
    html = _equalizador_html()
    assert '<script src="https://telegram.org/js/telegram-web-app.js"></script>' not in html
    assert '<script async src="https://telegram.org/js/telegram-web-app.js"' in html
    assert 'panel_head_js_started' in html
    assert 'panel_dom_content_loaded' in html
    assert 'panel_bottom_script_not_started' in html
    assert 'Telegram.WebApp ausente após 1.2s' in html
    assert 'id="panel_boot_debug"' in html


def test_phase137_4_panel_main_bootstrap_has_ping_timeout_and_visible_stages() -> None:
    script = _equalizador_script()
    assert 'panel_js_started' in script
    assert 'PANEL_FETCH_TIMEOUT_MS = 8000' in script
    assert 'const fetchWithTimeout = async (url, options, ms)' in script
    assert '/equalizador/api/public/ping?panel=1&ts=' in script
    assert 'panel_ping_started' in script
    assert 'panel_ping_done' in script
    assert 'panel_api_me_started' in script
    assert 'panel_api_me_done' in script
    assert 'panel_bootstrap_failed' in script


def test_phase137_4_panel_preserves_login_and_ui_state_across_updates() -> None:
    script = _equalizador_script()
    assert 'const STATE_KEY = "tr4_equalizador_state_v1"' in script
    assert 'localStorage.setItem(SESSION_KEY, value)' in script
    assert 'localStorage.setItem("tr4_public_eqs", value)' in script
    assert 'sessionStorage.getItem(SESSION_KEY) || localStorage.getItem("tr4_public_eqs") || localStorage.getItem(SESSION_KEY)' in script
    assert 'rememberPanelState({ palco_ref: String(palco && palco.grp_ref || "") })' in script
    assert 'rememberPanelState({ view_id: id })' in script
    assert 'const restoredPalco = savedPalcoRef ? (palcosDisponiveis || []).find' in script
    assert 'if (status === 401 || status === 403) setStoredSession("")' in script
    assert 'A sessão local foi preservada para nova tentativa.' in script


def test_phase137_4_panel_javascript_passes_node_check(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node não disponível neste ambiente")
    panel_js = tmp_path / "phase137_4_equalizador.js"
    public_js = tmp_path / "phase137_4_public_player.js"
    panel_js.write_text(_equalizador_script(), encoding="utf-8")
    text = _router_text()
    public_html = text[text.index('_PUBLIC_MUSIC_HTML = """') + len('_PUBLIC_MUSIC_HTML = """'):text.index('"""\n\n@router.get("/player"')]
    start = public_html.index("<script>") + len("<script>")
    end = public_html.rindex("</script>")
    public_js.write_text(public_html[start:end], encoding="utf-8")
    subprocess.run([node, "--check", str(panel_js)], check=True)
    subprocess.run([node, "--check", str(public_js)], check=True)
