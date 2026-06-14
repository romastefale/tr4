from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def _block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_playing_inline_preserva_legenda_original():
    block = _block("_render_playing")
    assert "_track_id, caption, cover, _keyboard, _card_emoji = payload" in block
    assert "safe_caption = _strip_links(caption)" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block


def test_tly_inline_pesquisa_nome_sem_exigir_conexao():
    block = _block("_render_tly")
    assert "if not item.arg and not is_user_connected(item.user_id):" in block
    assert "track = await _resolve_inline_tly_track(item)" in block
    assert "await lyrics_service.get_snippet" not in block
    assert "caption = header" in block
    assert "deferred_artist=artist_raw" in block
    assert "deferred_title=track_name_raw" in block


def test_tly_tem_busca_por_arg_e_fallback_para_atual():
    assert "async def _resolve_inline_tly_track" in INLINE
    assert "if item.arg:" in INLINE
    assert "return await _search_spotify_inline_track(item.arg)" in INLINE
    assert "return await music_service.get_current_or_last_played(item.user_id)" in INLINE


def test_deferred_da_letra_agendado_no_sucesso_da_midia():
    block = _block("_edit_inline_rendered")
    media_start = block.index("await bot.edit_message_media")
    media_return = block.index("return", media_start)
    media_success = block[media_start:media_return]
    assert "asyncio.create_task" in media_success
    assert "_edit_inline_caption_when_lyrics_ready" in media_success
    assert "as_media=True" in media_success
