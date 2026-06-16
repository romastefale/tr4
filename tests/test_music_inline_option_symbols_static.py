from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")


def test_inline_option_titles_use_only_text_symbols():
    assert '"playing": "♫ Música atual"' in INLINE
    assert '"tly": "✎ Trecho da letra"' in INLINE
    assert '"tcanvas": "▣ Canvas da música"' in INLINE
    assert '"week": "▦ Extrato semanal"' in INLINE
    assert '"month": "◫ Extrato mensal"' in INLINE
    assert '"mosaic": "✦ Mosaico musical"' in INLINE


def test_thumbnail_funcional_usa_icones_locais_sem_cdn_externo():
    assert "thumbnail_url=_inline_thumb_url(item_kind)" in INLINE
    assert "_KIND_THUMBNAIL_URL" not in INLINE
    assert "cdn.jsdelivr.net/gh/twitter/twemoji" not in INLINE
    assert "dummyimage.com" not in INLINE
