from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def _block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_tly_pesquisado_usa_layout_com_nome_linha_e_contador_real():
    block = _block("_render_tly")
    assert "header = _format_inline_music_header(name_part, track_name, artist, total_plays)" in block
    assert 'header = f"{name_part} · ♫ {track_name} — {artist}"' not in block
    assert 'header = f"{name_part}\\n♫ {track_name} — {artist}"' not in block


def test_playing_inline_tambem_usa_layout_publico_novo_sem_link():
    block = _block("_render_playing")
    assert "track_id, _caption, cover, _keyboard, _card_emoji = payload" in block
    assert "caption = _format_inline_music_header(name_part, track_name, artist, total_plays)" in block
    assert "safe_caption = _strip_links(caption)" in block


def test_tly_continua_com_nome_musica_artista_e_sem_link():
    block = _block("_render_tly")
    assert "name_part = _inline_name_style(item.display_name or \"Usuário\")" in block
    assert "track_name, artist, _track_url, cover = _track_label(track)" in block
    assert "safe_caption = _strip_links(caption)" in block
    assert "href=" not in block
