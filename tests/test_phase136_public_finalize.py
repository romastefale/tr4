from pathlib import Path


def _router_text() -> str:
    return Path("app/equalizador/router.py").read_text(encoding="utf-8")


def _html_block(text: str) -> str:
    start = text.index('_PUBLIC_MUSIC_HTML = """') + len('_PUBLIC_MUSIC_HTML = """')
    end = text.index('"""\n\n@router.get("/player"', start)
    return text[start:end]


def _script_block(html: str) -> str:
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    return html[start:end]


def test_phase136_html_has_internal_command_runtime():
    text = _router_text()
    html = _html_block(text)
    script = _script_block(html)
    assert 'function hide(id,shouldHide)' in script
    assert script.index('function hide(id,shouldHide)') < script.index('function showBotFallback')
    assert 'runPublicCommand' in script
    assert '/equalizador/api/public/command/' in script
    assert '?start=cmd_' not in script
    assert 'cmd_' not in script
    assert '_get_bot' not in text


def test_phase136_backend_command_endpoint_exists():
    text = _router_text()
    assert '@router.get("/api/public/command/{command_name}")' in text
    assert 'lastfm_weekly_service.build_capsule' in text
    assert 'lastfm_capsule_service.build_capsule' in text
    assert 'lastfm_group_service.build_group_capsule' in text
    assert 'getChatMember' in text
    assert 'data:image' in text


def test_phase136_embedded_js_guardrails():
    html = _html_block(_router_text())
    script = _script_block(html)
    assert '"""' not in html
    assert 'player_js_started' in script
    assert 'player_unhandledrejection' in script
    assert 'player_command_failed' in script
    assert 'node --check' not in script
