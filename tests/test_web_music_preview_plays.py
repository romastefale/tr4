from __future__ import annotations

import pytest

from app.bot import music_command_runner as runner


@pytest.mark.asyncio
async def test_current_track_preview_uses_lastfm_userplaycount(monkeypatch):
    async def fake_current_or_last_played(user_id: int):
        assert user_id == 123
        return {
            "track_id": "lfm:test",
            "track_name": "Song A",
            "artist": "Artist A",
            "spotify_url": "https://open.spotify.com/track/1",
            "album_image_url": "https://example.test/cover.jpg",
        }

    async def fake_lastfm_playcount(user_id: int, artist: str, track_name: str):
        assert (user_id, artist, track_name) == (123, "Artist A", "Song A")
        return 17

    monkeypatch.setattr(runner, "is_user_connected", lambda user_id: True)
    monkeypatch.setattr(runner.music_service, "get_current_or_last_played", fake_current_or_last_played)
    monkeypatch.setattr(runner.lastfm_service, "get_user_track_playcount", fake_lastfm_playcount)

    data = await runner.current_track_preview(123)

    assert data["available"] is True
    assert data["user_plays"] == 17
    assert data["plays_source"] == "lastfm"


@pytest.mark.asyncio
async def test_current_track_preview_falls_back_to_local_user_count(monkeypatch):
    async def fake_current_or_last_played(user_id: int):
        return {
            "track_id": "spotify:test",
            "track_name": "Song B",
            "artist": "Artist B",
        }

    async def fake_lastfm_playcount(user_id: int, artist: str, track_name: str):
        return None

    async def fake_local_count(user_id: int, track_id: str):
        assert (user_id, track_id) == (456, "spotify:test")
        return 3

    monkeypatch.setattr(runner, "is_user_connected", lambda user_id: True)
    monkeypatch.setattr(runner.music_service, "get_current_or_last_played", fake_current_or_last_played)
    monkeypatch.setattr(runner.lastfm_service, "get_user_track_playcount", fake_lastfm_playcount)
    monkeypatch.setattr(runner.likes_service, "get_user_play_count", fake_local_count)

    data = await runner.current_track_preview(456)

    assert data["available"] is True
    assert data["user_plays"] == 3
    assert data["plays_source"] == "local"
