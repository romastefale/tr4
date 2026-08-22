from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_playing_payload_layout_global_sem_linha_de_likes():
    telegram = read("app/bot/telegram.py")
    assert 'return await likes_service.get_user_play_count(user_id, track_id), "local_user"' in telegram
    assert 'play_prefix = f"♫ <code>{total_plays}</code> · " if isinstance(total_plays, int) and total_plays >= 0 else "♫ "' in telegram
    assert 'f"<b><a href=\\"{html.escape(user_link)}\\">{display_name}</a></b>\\n"' in telegram
    assert ' · ♥ <code>{user_total_likes}</code>' not in telegram
    assert 'get_track_play_count(track_id), "local"' not in telegram


def test_inline_legacy_photo_helper_removed():
    telegram = read("app/bot/telegram.py")
    assert "InlineQueryResultCachedPhoto" not in telegram
    assert "async def _inline_photo_result_for_cover" not in telegram
    assert "await _inline_photo_result_for_cover(" not in telegram
    # cover cache remains for /playing and cards
    assert "await cover_cache_service.resolve_photo" in telegram


def test_tstory_fallback_remove_file_id_velho_e_tenta_bytes_originais():
    tstory = read("app/bot/tstory.py")
    assert "TSTORY_FALLBACK_COVER_SEND_FAILED" in tstory
    assert "await cover_cache_service.forget" in tstory
    assert 'photo=BufferedInputFile(cover_bytes, filename="cover.jpg")' in tstory
