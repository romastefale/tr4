from __future__ import annotations

import py_compile
import shutil
import subprocess
from pathlib import Path

import pytest

ROUTER = Path("app/equalizador/router.py")
TELEGRAM = Path("app/bot/telegram.py")


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


def test_phase137_1_sources_compile() -> None:
    py_compile.compile(str(ROUTER), doraise=True)
    py_compile.compile(str(TELEGRAM), doraise=True)


def test_phase137_1_brand_pill_refreshes_session_without_full_reload() -> None:
    html = _html_block()
    script = _public_script()
    assert 'id="refreshSessionBtn"' in html
    assert 'aria-label="Recarregar música e sessão"' in html
    assert 'function refreshPublicSession()' in script
    assert '/equalizador/api/public/me' in script
    assert '/equalizador/api/public/home' in script
    assert '/equalizador/api/public/playing-preview' in script
    assert 'location.reload' not in script


def test_phase137_1_now_card_has_half_scale_adaptive_title_classes() -> None:
    html = _html_block()
    script = _public_script()
    assert 'font-size:clamp(24px,8.5vw,39px)' in html
    assert '.track-title.len-medium' in html
    assert '.track-title.len-long' in html
    assert '.track-title.len-xlong' in html
    assert '-webkit-line-clamp:3' in html
    assert 'function titleClass(value)' in script
    assert 'titleEl.className="track-title "+titleClass(title)' in script


def test_phase137_1_result_renders_rich_text_and_full_image_with_download() -> None:
    html = _html_block()
    script = _public_script()
    assert 'id="resultImageLink"' in html
    assert 'height:auto;object-fit:contain' in html
    assert 'max-height:230px' not in html
    assert 'function sanitizeRichText(value)' in script
    assert 'function setBodyRich(el,value)' in script
    assert 'setBodyRich(body,data.text||data.message||"")' in script
    assert 'body.textContent=data.text' not in script
    assert 'function downloadResult()' in script
    assert 'downloadFile' in script


def test_phase137_1_command_copy_uses_web_app_data_and_backend_handler_exists() -> None:
    script = _public_script()
    bot = TELEGRAM.read_text(encoding="utf-8")
    assert 'function sendCommandCopy(command)' in script
    assert 'public_command_copy' in script
    assert 'tg.sendData(payload)' in script
    assert '@dp.message(F.web_app_data)' in bot
    assert 'json.loads(raw)' in bot
    for handler in ('_weekfm_handler', '_monthfm_handler', '_tcanvas_handler', '_tstory_handler', '_tly_handler', '_tnow_handler'):
        assert handler in bot


def test_phase137_1_backend_mosaic_is_real_not_static_fallback_text() -> None:
    text = _router_text()
    assert 'O Mosaico reaproveita o comando tnow' not in text
    assert 'async def _public_tnow_result' in text
    assert '_resolve_now_playing' in text
    assert 'render_tnow_card(entries)' in text
    assert 'getChatMember' in text


def test_phase137_1_media_results_expose_real_preview_and_download_metadata() -> None:
    text = _router_text()
    assert 'async def _public_track_media_result' in text
    assert 'spotify_canvas_service.get_canvas_url' in text
    assert 'render_tstory_full' in text
    assert 'download_url=canvas_url or cover_url' in text
    assert 'command_copy="/tcanvas"' in text
    assert 'command_copy="/tstory"' in text


def test_phase137_1_public_javascript_passes_node_check(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node não disponível neste ambiente")
    public_js = tmp_path / "phase137_1_public_player.js"
    public_js.write_text(_public_script(), encoding="utf-8")
    subprocess.run([node, "--check", str(public_js)], check=True)
