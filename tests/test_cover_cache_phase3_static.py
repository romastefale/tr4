from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cover_cache_model_service_and_settings_exist():
    model = read("app/models/cover_file.py")
    service = read("app/services/cover_cache.py")
    settings = read("app/config/settings.py")
    db = read("app/db/database.py")
    assert 'class CoverFile(Base)' in model
    assert '__tablename__ = "cover_files"' in model
    for field in ("cache_key", "spotify_track_id", "cover_url", "cover_hash", "file_id", "file_unique_id"):
        assert field in model
    assert "class CoverCacheService" in service
    assert "async def resolve_photo" in service
    assert "async def forget" in service
    assert "COVER_CACHE_ENABLED" in settings
    assert "COVER_CACHE_CHANNEL_ID" in settings
    assert "CREATE TABLE IF NOT EXISTS cover_files" in db
    assert "from app.models.cover_file import CoverFile" in db


def test_cover_cache_used_by_main_music_entrypoints():
    telegram = read("app/bot/telegram.py")
    tly = read("app/bot/tly.py")
    inline = read("app/bot/music_inline.py")
    runner = read("app/bot/music_command_runner.py")
    canvas = read("app/bot/canvas_delivery.py")
    extras = read("app/bot/music_extras.py")
    radiofm = read("app/bot/radiofm.py")
    for source in (telegram, tly, inline, runner, canvas, extras, radiofm):
        assert "cover_cache_service" in source
    assert "track_id=rendered.track_id" in inline
    assert "track_id=track_id" in tly
    assert "track_id=track_id" in telegram


def test_tly_command_layout_uses_line_break_and_real_count_guard():
    telegram = read("app/bot/telegram.py")
    assert 'play_prefix = f"♫ <code>{total_plays}</code> · " if isinstance(total_plays, int) and total_plays >= 0 else "♫ "' in telegram
    assert 'header = f"{name_part}\\n{play_prefix}{track_part} — <i>{artist}</i>"' in telegram
