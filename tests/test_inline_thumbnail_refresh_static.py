from pathlib import Path


def test_inline_icon_assets_are_png():
    icon_dir = Path("app/static/inline_icons")
    expected = ["playing.png", "tly.png", "tcanvas.png", "week.png", "month.png", "mosaic.png"]
    for name in expected:
        data = (icon_dir / name).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_inline_thumb_url_uses_revision_query():
    source = Path("app/bot/music_inline.py").read_text(encoding="utf-8")
    assert "hashlib.sha1" in source
    assert '?v={rev}' in source or 'png?v=' in source
    assert '_INLINE_ICON_REVISIONS' in source
