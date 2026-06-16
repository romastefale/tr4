from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def _render_tly_block() -> str:
    start = INLINE.index("async def _render_tly")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_inline_tly_caption_uses_real_play_count_format_with_fallback():
    block = _render_tly_block()
    helper_start = INLINE.index("def _format_inline_music_header")
    helper_end = INLINE.find("\n\ndef ", helper_start + 1)
    helper = INLINE[helper_start:helper_end]
    assert '_inline_name_style(item.display_name or "Usuário")' in block
    assert "header = _format_inline_music_header(name_part, track_name, artist, total_plays)" in block
    assert 'play_prefix = f"♫ {total_plays} · " if isinstance(total_plays, int) and total_plays >= 0 else "♫ "' in helper
    assert 'return f"{name_part}\\n{play_prefix}{track_name} — {artist}"' in helper
    assert "safe_caption = _strip_links(caption)" in block
    assert "href=" not in block
    assert "<i>{artist}</i>" not in block


def test_inline_name_style_matches_requested_pi_sample():
    assert "_SANS_BOLD_ITALIC_UPPER_OFFSET" in INLINE
    assert "_SANS_BOLD_ITALIC_LOWER_OFFSET" in INLINE
    assert "0x1D63C" in INLINE
    assert "0x1D656" in INLINE
