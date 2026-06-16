from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "app" / "bot" / "music_command_runner.py").read_text(encoding="utf-8")


def test_tnow_group_uses_chat_scope_and_private_universal_requires_owner():
    assert "chat = status.chat if status.chat.type in _GROUP_TYPES else None" in TNOW
    assert "if scope == \"universal\" and not is_code_owner(requester_id):" in TNOW
    assert "entries = await _gather_entries(status.bot, chat=chat)" in TNOW
    assert "_finish_tnow(status, requester_id=message.from_user.id)" in TNOW


def test_tnow_snapshot_is_scoped_by_group_or_universal():
    assert "TNOW_SNAPSHOT_TTL_SECONDS" in TNOW
    assert 'return f"tnow:group:{int(chat.id)}"' in TNOW
    assert 'return "tnow:universal"' in TNOW
    assert "TNOW_SNAPSHOT_HIT" in TNOW


def test_tnow_display_name_prioritizes_lastfm_before_telegram():
    block = TNOW.split("async def _display_name", 1)[1].split("async def _build_entry", 1)[0]
    assert block.index("lastfm_username = _lastfm_display_name(user_id)") < block.index("chat = await bot.get_chat(user_id)")


def test_tnow_card_captures_card_element_not_full_page():
    assert 'page.locator(".card").first' in CARD
    assert "card.screenshot" in CARD
    assert "full_page=True" not in CARD


def test_music_inline_is_owner_only_for_all_kinds():
    assert "MUSIC_INLINE_BLOCKED_NON_OWNER" in INLINE
    assert "MUSIC_INLINE_RENDER_BLOCKED_NON_OWNER" in INLINE
    assert "allowed = _is_owner(query.from_user.id)" in INLINE


def test_universal_tnow_executor_rechecks_owner():
    assert "WEB_UNIVERSAL_TNOW_REJECTED_NON_OWNER" in RUNNER
    assert "if not is_code_owner(requester_id):" in RUNNER
    assert "Mosaico universal é exclusivo do dono do código." in RUNNER
