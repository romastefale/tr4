from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")


def _async_block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_inline_menu_usa_icones_png_locais_com_cache_bust():
    assert "def _inline_thumb_url" in INLINE
    assert "_INLINE_ICON_REVISIONS" in INLINE
    assert "hashlib.sha1" in INLINE
    assert "thumbnail_url=_inline_thumb_url(item_kind)" in INLINE
    assert "thumbnail_width=96" in INLINE
    assert "thumbnail_height=96" in INLINE
    assert "dummyimage.com" not in INLINE


def test_todos_os_kinds_tem_thumbnail_neon_local():
    icon_dir = ROOT / "app" / "static" / "inline_icons"
    for kind in ("playing", "tly", "tcanvas", "week", "month", "mosaic"):
        path = icon_dir / f"{kind}.png"
        data = path.read_bytes()
        assert data.startswith(PNG_SIGNATURE), f"PNG inválido: {kind}"
        assert len(data) > 100_000, f"ícone pequeno demais: {kind}"


def test_fluxo_musica_atual_nao_mudou():
    block = _async_block("_render_playing")
    assert "track_id, _caption, cover, _keyboard, _card_emoji = payload" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block


def test_layout_publico_corrigido_continua_presente():
    assert 'caption = f"{name_part}\\n♫ {html.escape(hit.title)} — {html.escape(hit.artist)}"' in TELEGRAM
    assert 'caption = f"<b>{html.escape(hit.title)}</b> - <i>{html.escape(hit.artist)}</i>"' not in TELEGRAM
