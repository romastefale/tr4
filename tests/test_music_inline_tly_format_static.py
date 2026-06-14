from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def _render_tly_block() -> str:
    start = INLINE.index("async def _render_tly")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_inline_tly_caption_uses_requested_format_without_links_or_count():
    block = _render_tly_block()
    assert '_inline_name_style(item.display_name or "Usuário")' in block
    assert 'header = f"{name_part} · ♫ {track_name} — {artist}"' in block
    assert "safe_caption = _strip_links(caption)" in block
    assert "href=" not in block
    assert "<i>{artist}</i>" not in block
    assert "♫ {total_plays}" not in block


def test_inline_name_style_matches_requested_pi_sample():
    assert "_SANS_BOLD_ITALIC_UPPER_OFFSET" in INLINE
    assert "_SANS_BOLD_ITALIC_LOWER_OFFSET" in INLINE
    assert "0x1D63C" in INLINE
    assert "0x1D656" in INLINE
