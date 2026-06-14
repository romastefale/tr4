from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def test_inline_public_legacy_caption_layout_corrigido():
    assert "def _inline_public_name_style" in TELEGRAM
    assert 'caption = f"{name_part}\\n♫ {html.escape(hit.title)} — {html.escape(hit.artist)}"' in TELEGRAM
    assert 'caption = f"<b>{html.escape(hit.title)}</b> - <i>{html.escape(hit.artist)}</i>"' not in TELEGRAM


def test_inline_public_define_name_part_no_loop():
    assert 'name_part = _inline_public_name_style(query.from_user.full_name or "Usuário")' in TELEGRAM


def test_musica_atual_playing_preservada_no_music_inline():
    start = INLINE.index("async def _render_playing")
    end = INLINE.find("\n\nasync def ", start + 1)
    block = INLINE[start:end if end > 0 else len(INLINE)]
    assert "_track_id, caption, cover, _keyboard, _card_emoji = payload" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block


def test_build_playing_payload_nao_foi_alterado():
    assert 'f"♫ <code>{total_plays}</code> · <b>{track_part}</b> — <i>{artist}</i>"' in TELEGRAM
