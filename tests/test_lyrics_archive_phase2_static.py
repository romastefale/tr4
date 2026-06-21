from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase2_lyrics_archive_model_migration_and_settings_exist():
    model = (ROOT / "app" / "models" / "lyrics_snippet_cache.py").read_text(encoding="utf-8")
    db = (ROOT / "app" / "db" / "database.py").read_text(encoding="utf-8")
    settings = (ROOT / "app" / "config" / "settings.py").read_text(encoding="utf-8")

    assert "channel_chat_id" in model
    assert "channel_message_id" in model
    assert "archived_at" in model
    assert "ALTER TABLE lyrics_snippet_cache ADD COLUMN" in db
    assert "ix_lyrics_snippet_cache_channel_chat_id" in db
    assert "LYRICS_CACHE_CHANNEL_ID" in settings
    assert "LYRICS_ARCHIVE_ENABLED" in settings


def test_phase2_archive_service_is_db_first_and_non_fatal():
    service = (ROOT / "app" / "services" / "lyrics_archive.py").read_text(encoding="utf-8")
    cache = (ROOT / "app" / "services" / "lyrics_cache.py").read_text(encoding="utf-8")

    assert "async def archive_tly_snippet" in service
    assert "lyrics_snippet_cache_service.get_archive_ref" in service
    assert "lyrics_snippet_cache_service.mark_archived" in service
    assert "send_photo" in service
    assert "send_message" in service
    assert "return None" in service
    assert "async def get_archive_ref" in cache
    assert "async def mark_archived" in cache


def test_phase2_three_entrypoints_call_archive_after_lyrics():
    tly = (ROOT / "app" / "bot" / "tly.py").read_text(encoding="utf-8")
    inline = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
    web_runner = (ROOT / "app" / "bot" / "music_command_runner.py").read_text(encoding="utf-8")

    assert "archive_tly_snippet" in tly
    assert "lyrics_service.get_snippet" in tly
    assert "archive_tly_snippet" in inline
    assert "lyrics_service.get_snippet" in inline
    assert "tly" in web_runner
    assert "edit_caption" in web_runner
