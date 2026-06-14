from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TLY = (ROOT / "app" / "bot" / "tly.py").read_text(encoding="utf-8")
LYRICS = (ROOT / "app" / "services" / "lyrics.py").read_text(encoding="utf-8")
INLINE_PATH = ROOT / "app" / "bot" / "music_inline.py"
INLINE = INLINE_PATH.read_text(encoding="utf-8") if INLINE_PATH.exists() else ""


def test_tly_sends_cover_before_lyrics_and_never_uses_canvas():
    assert "deliver_canvas" not in TLY
    assert "await _send_initial_tly" in TLY
    assert "asyncio.create_task" in TLY
    assert "edit_caption" in TLY
    assert "<blockquote>" in TLY
    assert "expandable" not in TLY
    assert "TLY_COVER_SEND_FAILED" in TLY


def test_lyrics_timeout_and_exc_binding_are_safe():
    assert "LYRICS_TIMEOUT_SECONDS = 5.0" in LYRICS
    if "type(exc).__name__" in LYRICS:
        assert "except Exception as exc" in LYRICS
    assert not re.search(r"except Exception:\n\s+logger\.warning\([^\n]*type\(exc\)", LYRICS)


def test_lrclib_is_prioritized_when_present():
    if "_fetch_lrclib" not in LYRICS:
        return
    lrclib_pos = LYRICS.find("result = await self._fetch_lrclib")
    ovh_pos = LYRICS.find("result = await self._fetch(a, t)")
    assert lrclib_pos != -1 and ovh_pos != -1 and lrclib_pos < ovh_pos


def test_inline_tly_is_cover_first_when_inline_file_exists():
    if not INLINE:
        return
    assert "deferred_artist" in INLINE
    assert "_edit_inline_caption_when_lyrics_ready" in INLINE
    assert "<blockquote>" in INLINE

def test_lyrics_background_has_more_patience_without_long_negative_cache():
    assert "LYRICS_TIMEOUT_SECONDS = 5.0" in LYRICS
    assert "LYRICS_NEGATIVE_TTL_SECONDS = 60" in LYRICS
