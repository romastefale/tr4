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

def test_empty_inline_query_shows_clickable_menu():
    assert "_INLINE_MENU_KINDS" in INLINE
    assert 'if not kind:' in INLINE
    assert "await query.answer(results, cache_time=1, is_personal=True)" in INLINE
    for token in ('"playing"', '"tly"', '"week"', '"month"', '"mosaic"'):
        assert token in INLINE


def test_inline_loading_result_forces_inline_message_id():
    assert "InlineKeyboardButton" in INLINE
    assert "InlineKeyboardMarkup" in INLINE
    assert "reply_markup=_build_loading_markup(result_id)" in INLINE
    assert "mi:render:" in INLINE


def test_inline_final_edit_removes_loading_keyboard():
    assert "edit_message_reply_markup" in INLINE
    assert "reply_markup=None" in INLINE
    assert "_edit_inline_rendered" in INLINE

def test_inline_render_button_is_inert_against_accidental_clicks():
    assert "MUSIC_INLINE_RENDER_BUTTON_TAPPED_IGNORED" in INLINE
    callback_block = INLINE.split("async def music_inline_render_callback", 1)[1].split("@router.chosen_inline_result", 1)[0]
    assert "await _render(" not in callback_block
    assert "await _edit_inline_rendered" not in callback_block


def test_inline_edit_ignores_message_not_modified():
    assert "message is not modified" in INLINE
    assert "MUSIC_INLINE_EDIT_MEDIA_NOT_MODIFIED" in INLINE
    assert "MUSIC_INLINE_EDIT_TEXT_NOT_MODIFIED" in INLINE


def test_tly_lyrics_failure_is_warning_fallback():
    assert "MUSIC_INLINE_TLY_LYRICS_SKIPPED" in INLINE
    assert "lyric_snippet = None" in INLINE
