from pathlib import Path


def test_phase133_public_front_bootstrap_is_resilient():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert "function escapeHtml(value)" in text
    assert "const SESSION_KEY = \"tr4_public_eqs\"" in text
    assert "Authorization: \"eqs \" + getStoredSession()" in text
    assert "apiHeaders = { Authorization: \"eqs \" + sessionToken }" in text
    assert 'api("/equalizador/api/public/playing-preview")' in text
    assert 'id="openBotBtn"' in text
    assert "https://t.me/tigraoRADIObot?startapp" in text
    assert '"sessao": create_equalizador_session(' in text


def test_phase133_public_command_grid_and_bridge_are_real():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="commandGrid"' in text
    assert 'data-command="/playing"' in text
    assert 'data-command="/nowp"' in text
    assert 'data-command="/myself"' in text
    assert 'data-command="/weekfm"' in text
    assert 'data-command="/monthfm"' in text
    assert 'data-command="/songcharts"' in text
    assert 'command === "/nowp"' in text
    assert 'command === "/songcharts"' in text


def test_phase133_webhook_unhandled_crash_is_removed():
    text = Path("app/bot/telegram.py").read_text(encoding="utf-8")
    assert "return UNHANDLED" not in text
    assert 'payload.startswith("cmd_")' in text
    assert 'command == "playing"' in text
    assert 'await _send_playing(message)' in text
    assert 'command == "weekfm"' in text
    assert 'command == "monthfm"' in text
