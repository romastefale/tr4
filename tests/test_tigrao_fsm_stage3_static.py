from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tigrao_flag_exists_and_default_false(monkeypatch) -> None:
    monkeypatch.delenv("TIGRAO_FSM_ENABLED", raising=False)
    import app.config.settings as settings
    settings = importlib.reload(settings)
    assert settings.TIGRAO_FSM_ENABLED is False
    assert settings.TIGRAO_FSM_MODERATOR_IDS == frozenset()


def test_main_imports_only_public_plugin_interface() -> None:
    main_py = read("app/main.py")
    assert "from app.plugins.tigrao_fsm import build_tigrao_fsm_plugin" in main_py
    forbidden = [
        "app.plugins.tigrao_fsm.runtime",
        "app.plugins.tigrao_fsm.routers",
        "app.plugins.tigrao_fsm.keyboards",
        "app.plugins.tigrao_fsm.storage",
        "app.plugins.tigrao_fsm.services",
    ]
    for item in forbidden:
        assert item not in main_py


def test_mount_and_before_dispatch_conditioned_to_flag() -> None:
    main_py = read("app/main.py")
    assert "if TIGRAO_FSM_ENABLED and tigrao_plugin is not None:\n                tigrao_plugin.mount(dispatcher)" in main_py
    assert "if TIGRAO_FSM_ENABLED and tigrao_plugin is not None:\n            try:\n                tigrao_plugin.set_current_user" in main_py
    assert "consumed = await tigrao_plugin.before_dispatch(bot, update)" in main_py


def test_consumed_update_skips_feed_update_static() -> None:
    main_py = read("app/main.py")
    assert "if not consumed:\n            await dispatcher.feed_update(bot, update)" in main_py


def test_allowed_updates_extra_only_with_flag() -> None:
    main_py = read("app/main.py")
    helper = main_py.split("def _telegram_allowed_updates()", 1)[1].split("async def _configure_telegram_bot_background", 1)[0]
    assert 'base = set(dispatcher.resolve_used_update_types()) | {"chosen_inline_result"}' in helper
    assert "if TIGRAO_FSM_ENABLED:" in helper
    for update in ["chat_join_request", "chat_member", "message_reaction", "message_reaction_count", "callback_query"]:
        assert f'"{update}"' in helper


def test_group_tigrao_does_not_answer_publicly() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    group_branch = panel.split("        return\n    try:", 1)[1].split("@router.callback_query", 1)[0]
    assert "message.answer" not in group_branch
    assert "bot.send_message" in group_branch


def test_close_delete_with_edit_fallback() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    close_branch = panel.split('if action == "close":', 1)[1].split('if action in {"home", "back"}', 1)[0]
    assert "callback.message.delete()" in close_branch
    assert 'edit_text("Painel fechado.")' in close_branch


def test_group_callback_uses_session_index_not_raw_chat_id() -> None:
    keyboards = read("app/plugins/tigrao_fsm/keyboards.py")
    assert 'make_callback(session_id, f"g{idx}")' in keyboards
    assert "chat_id" not in 'make_callback(session_id, f"g{idx}")'


def test_music_forbidden_files_do_not_reference_tigrao() -> None:
    paths = [
        "app/bot/telegram.py",
        "app/bot/radiofm.py",
        "app/bot/tnow.py",
        "app/bot/tly.py",
        "app/bot/music_inline.py",
    ]
    paths.extend(str(p.relative_to(ROOT)) for p in (ROOT / "app/bot").glob("playing*.py"))
    paths.extend(str(p.relative_to(ROOT)) for p in (ROOT / "app/web_music").rglob("*.py"))
    for path in paths:
        if (ROOT / path).exists():
            assert "tigrao_fsm" not in read(path).lower()


def test_telegram_py_not_altered_for_tigrao() -> None:
    assert "tigrao_fsm" not in read("app/bot/telegram.py").lower()
