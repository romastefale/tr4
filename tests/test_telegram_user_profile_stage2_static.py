from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
WEB_AUTH = (ROOT / "app" / "web_music" / "auth.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "telegram_user_profiles.py").read_text(encoding="utf-8")
MODEL = (ROOT / "app" / "models" / "telegram_user_profile.py").read_text(encoding="utf-8")


def test_webapp_init_data_updates_telegram_profile():
    assert "telegram_user_profile_service.upsert_profile" in WEB_AUTH
    assert 'source="webapp_init_data"' in WEB_AUTH
    assert "photo_url=user.photo_url" in WEB_AUTH
    assert "language_code=user.language_code" in WEB_AUTH


def test_webhook_updates_profiles_from_all_user_surfaces():
    assert "def _remember_telegram_users_from_update" in MAIN
    assert "message" in MAIN and "callback_query" in MAIN and "inline_query" in MAIN
    assert "chosen_inline_result" in MAIN
    assert "telegram_user_profile_service.upsert_from_telegram_user" in MAIN
    assert "_remember_telegram_users_from_update(update)" in MAIN


def test_profile_service_does_not_use_musical_username_as_display_fallback():
    assert "def display_name_from_saved_profile" in SERVICE
    assert "async def resolve_music_display_name" in SERVICE
    resolver = SERVICE.split("async def resolve_music_display_name", 1)[1]
    assert "display_name_from_saved_profile" in resolver
    assert "bot.get_chat" in resolver
    assert "TPV_DEFAULT_LABEL" in resolver
    assert "lastfm_username" not in resolver.lower()


def test_profile_model_has_visual_identity_fields():
    for field in ("first_name", "last_name", "username", "full_name", "photo_url", "language_code", "source"):
        assert field in MODEL
