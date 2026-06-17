from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str | None = None) -> str:
    i = text.index(start)
    if end is None:
        return text[i:]
    j = text.index(end, i)
    return text[i:j]


def test_stage7_start_help_login_lastfm_user_texts_are_service_neutral():
    telegram = read("app/bot/telegram.py")
    user_surface = "\n".join(
        [
            _slice(telegram, "def _start_text", "def _help_text"),
            _slice(telegram, "def _help_text", "# Negrito unicode"),
            _slice(telegram, '@dp.message(Command("login"))', '@dp.message(Command("logout"))'),
            _slice(telegram, '@dp.message(Command("lastfm"))', '@dp.message(Command("lastfmoff"))'),
            _slice(telegram, "if payload == \"connect\":", "if payload == \"help\":"),
        ]
    )
    assert "/lastfm seu_usuario" in user_surface
    assert "/login" in user_surface
    assert "perfil musical" in user_surface
    assert "conta musical" in user_surface
    assert "Last.fm" not in user_surface
    assert "Last fm" not in user_surface
    assert "Spotify" not in user_surface


def test_stage7_not_connected_messages_explain_commands_only():
    connection = read("app/services/connection_check.py")
    runner = read("app/bot/music_command_runner.py")
    assert "/lastfm seu_usuario" in connection
    assert "/login" in runner
    hints = _slice(connection, "CONNECT_HINT_GROUP")
    preview = _slice(runner, "async def current_track_preview")
    for text in (hints, preview):
        assert "Last.fm" not in text
        assert "Last fm" not in text
        assert "Spotify" not in text


def test_stage7_web_player_does_not_render_provider_names_or_plays_source():
    player = read("app/web_music/player.html")
    render_track = _slice(player, "function renderTrack", "function updateCommandState")
    assert "plays_source" not in render_track
    assert "Last.fm" not in render_track
    assert "Last fm" not in render_track
    assert "Spotify" not in render_track


def test_stage7_identity_and_tpv_contract_remain_wired():
    tnow = read("app/bot/tnow.py")
    profiles = read("app/services/telegram_user_profiles.py")
    assert "resolve_music_display_name" in tnow
    assert "tnow_privacy_service.label_for" in profiles
    assert "display_name_from_saved_profile" in profiles
    resolver = _slice(profiles, "async def resolve_music_display_name")
    assert "bot.get_chat" in resolver
    assert "TPV_DEFAULT_LABEL" in resolver
    assert "lastfm_username" not in resolver.lower()


def test_stage7_adaptive_grid_contract_remains_non_destructive():
    tnow = read("app/bot/tnow.py")
    card = read("app/services/tnow_card.py")
    assert "selected_activities = eligible[:MAX_TILES]" in tnow
    assert "eligible[:slots]" not in tnow
    assert "eligible[:capacity]" not in tnow
    assert "empty_slots" in tnow
    assert "last.fm" not in card.lower()
    assert "provider-badge" not in card
