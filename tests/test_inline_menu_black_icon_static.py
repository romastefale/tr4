from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")


def _async_block(name: str) -> str:
    start = INLINE.index(f"async def {name}")
    end = INLINE.find("\n\nasync def ", start + 1)
    if end < 0:
        end = len(INLINE)
    return INLINE[start:end]


def test_inline_menu_lateral_tem_icone_preto_sobre_fundo_branco():
    assert "_INLINE_THUMB_URL" in INLINE
    assert "ffffff/000000" in INLINE
    assert "thumbnail_url=_INLINE_THUMB_URL.get(item_kind)" in INLINE
    assert "thumbnail_width=96" in INLINE
    assert "thumbnail_height=96" in INLINE


def test_todos_os_kinds_tem_thumbnail_monocromatica():
    for kind in ("playing", "tly", "week", "month", "mosaic"):
        assert f'"{kind}": "https://dummyimage.com/96x96/ffffff/000000.png&text=' in INLINE


def test_fluxo_musica_atual_nao_mudou():
    block = _async_block("_render_playing")
    assert "_track_id, caption, cover, _keyboard, _card_emoji = payload" in block
    assert 'caption = f"{name_part} · ♫ {track_name} — {artist}"' not in block


def test_layout_publico_corrigido_continua_presente():
    assert 'caption = f"{name_part}\\n♫ {html.escape(hit.title)} — {html.escape(hit.artist)}"' in TELEGRAM
    assert 'caption = f"<b>{html.escape(hit.title)}</b> - <i>{html.escape(hit.artist)}</i>"' not in TELEGRAM
