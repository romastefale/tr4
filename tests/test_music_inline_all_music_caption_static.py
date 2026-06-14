from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def _block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_playing_inline_uses_requested_public_caption_format():
    block = _block("_render_playing")
    assert '_inline_name_style(item.display_name or "Usuário")' in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' in block
    assert "build_playing_payload_for_user" in block
    assert "safe_caption = _strip_links(caption)" in block
    assert "♫ {total_plays}" not in block
    assert "<i>{artist}</i>" not in block


def test_tly_inline_uses_same_requested_public_caption_format():
    block = _block("_render_tly")
    assert '_inline_name_style(item.display_name or "Usuário")' in block
    assert 'header = f"{name_part} · ♫ {track_name} — {artist}"' in block
    assert "safe_caption = _strip_links(caption)" in block
    assert "♫ {total_plays}" not in block
    assert "<i>{artist}</i>" not in block


def test_no_link_markup_in_public_music_inline_captions():
    for name in ("_render_playing", "_render_tly"):
        block = _block(name)
        assert "href=" not in block
        assert "http://" not in block
        assert "https://" not in block
