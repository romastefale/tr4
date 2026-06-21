from pathlib import Path

from app.services.spotify_links import (
    extract_spotify_track_id,
    first_spotify_url,
    is_allowed_spotify_short_url,
    looks_like_spotify_track_reference,
)

ROOT = Path(__file__).resolve().parents[1]
VALID_ID = "6I9VzXrHxO9rA9A5euc8Ak"


def test_spotify_link_parser_accepts_official_track_url_and_uri():
    assert extract_spotify_track_id(f"https://open.spotify.com/track/{VALID_ID}?si=abc") == VALID_ID
    assert extract_spotify_track_id(f"http://open.spotify.com/track/{VALID_ID}") == VALID_ID
    assert extract_spotify_track_id(f"spotify:track:{VALID_ID}") == VALID_ID


def test_spotify_link_parser_accepts_regional_player_path():
    assert extract_spotify_track_id(f"https://open.spotify.com/intl-pt/track/{VALID_ID}?si=abc") == VALID_ID


def test_spotify_link_parser_detects_mobile_short_links_without_arbitrary_hosts():
    assert first_spotify_url("ouve aqui https://spotify.link/abc123") == "https://spotify.link/abc123"
    assert is_allowed_spotify_short_url("https://spotify.link/abc123")
    assert is_allowed_spotify_short_url("https://spotify.app.link/abc123")
    assert looks_like_spotify_track_reference("https://spotify.link/abc123")
    assert not looks_like_spotify_track_reference("https://example.com/track/6I9VzXrHxO9rA9A5euc8Ak")


def test_inline_query_routes_bare_spotify_link_to_tly_without_public_fallback():
    inline = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
    assert "looks_like_spotify_track_reference(value)" in inline
    assert 'return "tly", value' in inline
    assert "resolve_track_from_shared_link(raw_value)" in inline


def test_spotify_service_resolves_direct_and_short_links_safely():
    spotify = (ROOT / "app" / "services" / "spotify.py").read_text(encoding="utf-8")
    assert "async def resolve_track_from_shared_link" in spotify
    assert "extract_spotify_track_id(raw)" in spotify
    assert "is_allowed_spotify_short_url(raw)" in spotify
    assert "follow_redirects=True" in spotify
    assert "len(url) > 2048" in spotify
    assert 'params = {"market": market} if market else None' in spotify
    assert 'return await self.get_track_by_id(track_id, market="BR")' in spotify
