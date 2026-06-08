from pathlib import Path


def test_phase133_public_front_bootstrap_is_resilient():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert 'function escapeHtml(value)' in text
    assert 'function getStoredPublicSession()' in text
    assert 'if (!initData && !storedPublicSession)' in text
    assert 'apiHeaders = { Authorization: "eqs " + sessionToken }' in text
    assert 'api("/equalizador/api/public/playing-preview")' in text


def test_phase133_public_command_grid_and_bridge_are_real():
    router = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    bot = Path('app/bot/telegram.py').read_text(encoding='utf-8')
    assert 'id="commandGrid"' in router
    assert 'command === "/songcharts"' in router
    assert 'command === "/nowp"' in router
    assert 'cmd == "playing"' in bot
    assert 'cmd == "myself"' in bot
    assert 'cmd == "weekfm"' in bot
    assert 'cmd == "monthfm"' in bot


def test_phase133_unhandled_is_imported_when_used():
    bot = Path('app/bot/telegram.py').read_text(encoding='utf-8')
    if 'return UNHANDLED' in bot:
        assert 'from aiogram.dispatcher.event.bases import UNHANDLED' in bot
