from pathlib import Path


def test_lyrics_cache_model_and_migration_exist():
    model = Path("app/models/lyrics_snippet_cache.py").read_text(encoding="utf-8")
    db = Path("app/db/database.py").read_text(encoding="utf-8")

    assert "class LyricsSnippetCache" in model
    assert "__tablename__ = \"lyrics_snippet_cache\"" in model
    assert "snippet" in model
    assert "expires_at" in model
    assert "CREATE TABLE IF NOT EXISTS lyrics_snippet_cache" in db
    assert "ix_lyrics_snippet_cache_artist_norm" in db
    assert "from app.models.lyrics_snippet_cache import LyricsSnippetCache" in db


def test_lyrics_service_uses_persistent_cache_and_longer_timeout():
    source = Path("app/services/lyrics.py").read_text(encoding="utf-8")

    assert "LYRICS_TIMEOUT_SECONDS = 8.0" in source
    assert "lyrics_snippet_cache_service.get" in source
    assert "lyrics_snippet_cache_service.put" in source
    assert "Fluxos comando normal, inline e WebApp" in source


def test_three_tly_entrypoints_still_use_shared_lyrics_service():
    tly = Path("app/bot/tly.py").read_text(encoding="utf-8")
    inline = Path("app/bot/music_inline.py").read_text(encoding="utf-8")
    web_runner = Path("app/bot/music_command_runner.py").read_text(encoding="utf-8")

    assert "lyrics_service.get_snippet" in tly
    assert "lyrics_service.get_snippet" in inline
    assert "execute_group_music_command" in web_runner
    assert "tly" in web_runner
