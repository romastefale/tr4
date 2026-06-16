from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_tcanvas_entra_na_lista_inline_com_icone_local():
    assert '"tcanvas": "tcanvas"' in INLINE
    assert '"canvas": "tcanvas"' in INLINE
    assert '"tcanvas": "▣ Canvas da música"' in INLINE
    assert '"tcanvas": "Gerando Canvas da música..."' in INLINE
    assert '_INLINE_MENU_KINDS: tuple[str, ...] = ("playing", "tly", "tcanvas", "week", "month", "mosaic")' in INLINE
    assert '"tcanvas": "tcanvas.png"' in MAIN
    path = ROOT / "app" / "static" / "inline_icons" / "tcanvas.png"
    assert path.exists()
    data = path.read_bytes()
    assert data.startswith(bytes.fromhex("89504e470d0a1a0a"))
    assert len(data) > 100_000


def test_tcanvas_inline_usa_fluxo_canvas_validado_com_fallback():
    assert "InputMediaVideo" in INLINE
    assert "async def _render_tcanvas" in INLINE
    assert "async def _canvas_file_id_for_inline" in INLINE
    block = _block("_canvas_file_id_for_inline")
    assert "get_canvas_with_preview_asset" in block
    assert "get_canvas_bytes_cached" in block
    assert "canvas_cache_service.get_file_id" in block
    assert "_cache_video_file_id" in block
    assert "canvas_cache_service.put" in block
    assert "MUSIC_INLINE_TCANVAS_RAW_ARCHIVED" in block
    assert "MUSIC_INLINE_TCANVAS_AUDIO_SKIPPED" in block
    assert "MUSIC_INLINE_TCANVAS_RAW_SKIPPED" in block


def test_tcanvas_inline_nao_quebra_tly_pesquisado():
    assert "async def _resolve_inline_tly_track" in INLINE
    assert "return await _search_spotify_inline_track(item.arg)" in INLINE
    assert "async def _render_tly" in INLINE
    assert "deferred_artist=artist_raw" in INLINE


def test_inline_video_edit_usa_file_id_e_tem_fallback():
    block = _block("_edit_inline_rendered")
    assert "if rendered.video:" in block
    assert "InputMediaVideo(media=file_id" in block
    assert "MUSIC_INLINE_EDIT_VIDEO_FAILED_FALLBACK" in block
    assert "if rendered.photo:" in block
