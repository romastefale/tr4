from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def test_inline_public_legacy_removed():
    assert "def _inline_public_name_style" not in TELEGRAM
    assert "async def inline_public" not in TELEGRAM


def test_musica_atual_playing_preserva_payload_e_layout_inline_novo():
    start = INLINE.index("async def _render_playing")
    end = INLINE.find("\n\nasync def ", start + 1)
    block = INLINE[start:end if end > 0 else len(INLINE)]
    assert "track_id, _caption, cover, _keyboard, _card_emoji = payload" in block
    assert "caption = _format_inline_music_header(name_part, track_name, artist, total_plays)" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block


def test_build_playing_payload_layout_global_atualizado():
    assert 'f"<b><a href=\\"{html.escape(user_link)}\\">{display_name}</a></b>\\n"' in TELEGRAM
    assert 'f"{play_prefix}<b>{track_part}</b> — <i>{artist}</i>"' in TELEGRAM
    assert ' · ♥ <code>{user_total_likes}</code>' not in TELEGRAM
