from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def test_inline_icon_files_exist_and_are_pngs():
    icon_dir = ROOT / "app" / "static" / "inline_icons"
    for name in ("playing", "tly", "tcanvas", "week", "month", "mosaic"):
        path = icon_dir / f"{name}.png"
        assert path.exists(), f"ícone ausente: {name}"
        data = path.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) > 100


def test_main_serves_inline_icons_route():
    assert '@app.get("/inline-icons/{name}.png")' in MAIN
    assert 'media_type="image/png"' in MAIN
    assert "Cache-Control" in MAIN
    assert "_INLINE_ICON_FILES" in MAIN


def test_music_inline_usa_base_url_e_nao_dummyimage():
    assert "BASE_URL" in INLINE
    assert "def _inline_thumb_url" in INLINE
    assert 'return f"{base}/inline-icons/{kind}.png?v={rev}"' in INLINE
    assert "thumbnail_url=_inline_thumb_url(item_kind)" in INLINE
    assert "dummyimage.com" not in INLINE


def test_fluxo_musica_atual_preservado():
    start = INLINE.index("async def _render_playing")
    end = INLINE.find("\n\nasync def ", start + 1)
    block = INLINE[start:end if end > 0 else len(INLINE)]
    assert "track_id, _caption, cover, _keyboard, _card_emoji = payload" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block
