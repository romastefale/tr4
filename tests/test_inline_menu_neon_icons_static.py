from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")


def test_inline_neon_icons_exist_and_are_pngs_reais():
    icon_dir = ROOT / "app" / "static" / "inline_icons"
    for name in ("playing", "tly", "tcanvas", "week", "month", "mosaic"):
        path = icon_dir / f"{name}.png"
        assert path.exists(), f"ícone ausente: {name}"
        data = path.read_bytes()
        assert data.startswith(PNG_SIGNATURE), f"assinatura PNG inválida: {name}"
        assert len(data) > 100_000, f"ícone pequeno demais; parece placeholder antigo: {name}"


def test_inline_icon_route_and_usage_still_exist():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    inline = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")

    assert '/inline-icons/{name}.png' in main
    assert 'media_type="image/png"' in main
    assert "Cache-Control" in main
    assert "_INLINE_ICON_FILES" in main

    assert "def _inline_thumb_url" in inline
    assert 'return f"{base}/inline-icons/{kind}.png?v={rev}"' in inline
    assert "thumbnail_url=_inline_thumb_url(item_kind)" in inline
    assert "dummyimage.com" not in inline
