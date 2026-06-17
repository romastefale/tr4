from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_stage6_no_dotted_lastfm_in_production_texts():
    for rel in [
        "app/bot/setup_commands.py",
        "app/bot/telegram.py",
        "app/services/connection_check.py",
        "app/services/lastfm_weekly.py",
        "app/services/lastfm_capsule.py",
        "app/services/lastfm_group.py",
        "app/services/tnow_card.py",
    ]:
        assert "Last.fm" not in read(rel)


def test_stage6_connection_hints_explain_commands_without_service_names():
    text = read("app/services/connection_check.py")
    hints_start = text.index("CONNECT_HINT_GROUP")
    hints = text[hints_start:]
    assert "/lastfm seu_usuario" in hints
    assert "perfil musical" in hints
    assert "Last fm" not in hints
    assert "Last.fm" not in hints
    assert "Spotify" not in hints


def test_stage6_login_and_lastfm_surface_keep_commands_but_not_service_names():
    text = read("app/bot/telegram.py")
    assert "<code>/lastfm seu_usuario</code>" in text
    assert "<code>/login</code>" in text
    assert "Abrir autorização" in text
    # Interface principal não deve nomear os provedores; URLs técnicas podem existir em serviços.
    user_surface = "\n".join(
        line for line in text.splitlines()
        if "message.answer" in line or "_answer_with_effect" in line or "<code>/lastfm" in line or "<code>/login" in line
    )
    assert "Last fm" not in user_surface
    assert "Last.fm" not in user_surface
    assert "Spotify" not in user_surface


def test_stage6_tnow_display_name_uses_profile_or_user_not_music_username():
    text = read("app/bot/tnow.py")
    fn_start = text.index("async def _display_name")
    fn_end = text.index("async def _warm_cover_cache", fn_start)
    body = text[fn_start:fn_end]
    assert "resolve_music_display_name" in body
    assert "return str(lastfm_username).strip()" not in body
    assert "_lastfm_display_name" not in body
    assert "fallback_label=TPV_DEFAULT_LABEL" not in body


def test_stage6_tnow_grid_selects_all_valid_up_to_max_tiles():
    text = read("app/bot/tnow.py")
    assert "selected_activities = eligible[:MAX_TILES]" in text
    assert "eligible[:slots]" not in text
    assert "empty_slots" in text
    assert "capacity" in text


def test_stage6_tnow_card_does_not_render_provider_badge():
    text = read("app/services/tnow_card.py")
    lower = text.lower()
    assert "last.fm" not in lower
    assert "spotify" not in lower
    assert "provider-badge" not in lower
