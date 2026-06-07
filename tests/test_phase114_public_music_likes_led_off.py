from pathlib import Path

TELEGRAM = Path("app/bot/telegram.py").read_text(encoding="utf-8")
SETTINGS = Path("app/config/settings.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_music_reactions_disabled_by_default():
    assert 'TR4_MUSIC_REACTIONS_ENABLED = _bool_env("TR4_MUSIC_REACTIONS_ENABLED", False' in SETTINGS
    assert 'if not settings.TR4_MUSIC_REACTIONS_ENABLED or not emoji:' in TELEGRAM
    assert 'if not settings.TR4_MUSIC_REACTIONS_ENABLED:' in TELEGRAM


def test_public_caption_has_requested_layout_without_likes():
    assert ' · ♫ <code>{total_plays}</code>' in TELEGRAM
    assert '{track_part} — <i>{artist}</i>' in TELEGRAM
    assert '· ♥ <code>' not in TELEGRAM


def test_public_player_route_and_spotify_link_present():
    assert '@router.get("/player"' in ROUTER
    assert 'spotify_url' in ROUTER
    assert 'nowLine' in ROUTER
