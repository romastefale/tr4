from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")


def test_music_inline_registered_before_legacy_inline_handler():
    assert "from app.bot.music_inline import router as music_inline_router" in MAIN
    assert "dispatcher.include_router(music_inline_router)" in MAIN
    assert "not _is_music_inline_v2_format(q)" in TELEGRAM


def test_chosen_inline_result_is_allowed_update():
    assert '"chosen_inline_result"' in MAIN


def test_inline_final_caption_has_link_stripper_and_no_photo_url_result():
    assert "def _strip_links" in INLINE
    assert "https?://" in INLINE
    assert "tg://" in INLINE
    assert "t\\.me/" in INLINE
    assert "InlineQueryResultPhoto" not in INLINE
    assert "photo_url=" not in INLINE


def test_tly_inline_never_uses_canvas_delivery():
    assert "deliver_canvas" not in INLINE
    assert "InputMediaPhoto" in INLINE
    assert "_render_tly" in INLINE


def test_inline_scope_contains_expected_commands():
    for token in ("playing", "tly", "semanal", "mensal", "mosaico"):
        assert token in INLINE


def test_empty_inline_query_does_not_use_legacy_playing_photo_url():
    assert "if not raw:" in TELEGRAM
    assert "await query.answer([], cache_time=1, is_personal=True)" in TELEGRAM
    assert "query vazia não deve cair no legado /playing" in TELEGRAM
