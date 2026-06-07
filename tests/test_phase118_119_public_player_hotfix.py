from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_public_bot_photo_route_does_not_require_initdata():
    assert '@router.get("/api/public/bot/foto")' in ROUTER
    assert 'def public_bot_foto()' in ROUTER
    assert '"bot_photo_url": "/equalizador/api/public/bot/foto"' in ROUTER


def test_public_player_removes_technical_nowp_text():
    assert 'A publicação usa o fluxo já existente do bot' not in ROUTER
    assert 'publicação via /nowp' not in ROUTER
    assert '<div class="stats" id="stats">música atual</div>' in ROUTER


def test_public_track_uses_same_music_service_with_connection_guard():
    assert 'music_service.get_current_or_last_played(int(user_id))' in ROUTER
    assert 'is_user_connected(int(user_id))' in ROUTER
    assert 'music_account_not_connected' in ROUTER


def test_bot_image_has_fallback_on_error():
    assert 'function showBotFallback()' in ROUTER
    assert '$("botPhoto").onerror = showBotFallback' in ROUTER
