from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
PROFILE_SERVICE = (ROOT / "app" / "services" / "telegram_user_profiles.py").read_text(encoding="utf-8")


def test_tnow_display_name_uses_telegram_profile_service_not_musical_username():
    block = TNOW.split("async def _display_name", 1)[1].split("async def _warm_cover_cache", 1)[0]
    assert "resolve_music_display_name" in block
    assert "lastfm_username" in block  # compatibility parameter remains
    assert "return str(lastfm_username).strip()" not in block
    assert "lastfm_username = _lastfm_display_name(user_id)" not in block
    assert "return lastfm_username" not in block


def test_music_display_name_order_is_tpv_saved_telegram_get_chat_user():
    assert "private_label = tnow_privacy_service.label_for" in PROFILE_SERVICE
    assert "saved = self.display_name_from_saved_profile(user_id)" in PROFILE_SERVICE
    assert "chat = await bot.get_chat(user_id)" in PROFILE_SERVICE
    assert "return TPV_DEFAULT_LABEL" in PROFILE_SERVICE
    assert "Provedores musicais permanecem dados técnicos" in PROFILE_SERVICE


def test_profile_table_and_upsert_are_present():
    model = (ROOT / "app" / "models" / "telegram_user_profile.py").read_text(encoding="utf-8")
    database = (ROOT / "app" / "db" / "database.py").read_text(encoding="utf-8")
    assert "__tablename__ = \"telegram_user_profiles\"" in model
    assert "user_id" in model and "first_name" in model and "username" in model
    assert "CREATE TABLE IF NOT EXISTS telegram_user_profiles" in database
    assert "TelegramUserProfile" in database
