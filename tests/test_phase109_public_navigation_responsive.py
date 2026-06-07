from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase109_public_player_is_mobile_safe_and_search_driven():
    assert 'viewport-fit=cover' in ROUTER
    assert 'env(safe-area-inset-top)' in ROUTER
    assert 'max-height: 286px' in ROUTER
    assert 'Buscar grupo ou ação' in ROUTER
    assert 'group-list' in ROUTER


def test_phase109_public_nowp_error_is_structured_and_bot_photo_uses_internal_route():
    assert 'bot_photo_url' in ROUTER
    assert '/equalizador/api/bot/foto' in ROUTER
    assert 'telegram_publish_rejected' in ROUTER
    assert 'public_detail' in ROUTER
