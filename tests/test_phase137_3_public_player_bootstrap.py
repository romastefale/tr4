from pathlib import Path


def _router_text() -> str:
    return Path("app/equalizador/router.py").read_text(encoding="utf-8")


def _html_block(text: str) -> str:
    start = text.index('_PUBLIC_MUSIC_HTML = """') + len('_PUBLIC_MUSIC_HTML = """')
    end = text.index('"""\n\n@router.get("/player"', start)
    return text[start:end]


def test_phase137_3_telegram_script_is_not_blocking_head():
    html = _html_block(_router_text())
    assert '<script src="https://telegram.org/js/telegram-web-app.js"></script>' not in html
    assert '<script async src="https://telegram.org/js/telegram-web-app.js"' in html
    assert 'player_head_js_started' in html
    assert 'player_bottom_script_not_started' in html
    assert 'Telegram.WebApp ausente após 1.2s' in html


def test_phase137_3_calls_ready_early_and_keeps_phase136_script_contract():
    html = _html_block(_router_text())
    first_plain_script = html.index("<script>")
    main_script = html[first_plain_script:]
    assert 'function hide(id,shouldHide)' in main_script
    assert 'player_js_started' in main_script
    assert 'phase137_3' in main_script
    assert 'window.__TR4_READY_PLAYER("configure")' in main_script
    assert 'tg.ready()' in html


def test_phase137_3_has_public_ping_and_fetch_timeouts():
    text = _router_text()
    html = _html_block(text)
    assert '@router.get("/api/public/ping")' in text
    assert 'def public_music_ping()' in text
    assert 'phase": "137.3"' in text
    assert 'function fetchTimeout(path,opts,ms)' in html
    assert '/equalizador/api/public/ping?ts=' in html
    assert 'player_ping_started' in html
    assert 'player_ping_done' in html
    assert 'player_api_started' in html
    assert 'player_api_done' in html


def test_phase137_3_visible_diagnostic_for_stuck_loading():
    html = _html_block(_router_text())
    assert 'id="bootDebug"' in html
    assert 'JS principal iniciou. Testando conexão com o backend.' in html
    assert 'Sem initData/sessão. Se estiver em cliente alternativo, teste no Telegram oficial.' in html
    assert 'Falha no bootstrap:' in html
