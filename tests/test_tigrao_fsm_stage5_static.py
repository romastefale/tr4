from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_destructive_flags_exist_and_default_false() -> None:
    settings = read("app/config/settings.py")
    for name in [
        "TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED",
        "TIGRAO_FSM_DDX_HARD_ENABLED",
        "TIGRAO_FSM_REACTIONS_ENABLED",
    ]:
        assert f'{name} = _bool_env("{name}", False)' in settings


def test_destructive_actions_are_behind_flags_in_panel() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    assert "TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED" in panel
    assert "Ações destrutivas indisponíveis" in panel
    assert "TIGRAO_FSM_DDX_HARD_ENABLED" in panel
    assert "DDX hard indisponível" in panel
    assert "TIGRAO_FSM_REACTIONS_ENABLED" in panel


def test_action_callbacks_and_confirmation_exist() -> None:
    keyboards = read("app/plugins/tigrao_fsm/keyboards.py")
    for action in ["act", "ban", "unban", "mute1h", "mute24h", "muteforever", "unmute", "delmsg", "ddxadd", "ddxlist", "ddxremove"]:
        assert f'"{action}"' in keyboards
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    assert "pending_destructive_action" in panel
    assert "Confirmar ação" in panel
    assert "execute_destructive_action" in panel


def test_ddx_storage_and_runtime_are_present() -> None:
    storage = read("app/plugins/tigrao_fsm/storage.py")
    assert "CREATE TABLE IF NOT EXISTS tigrao_ddx_filters" in storage
    assert "create_ddx_filter" in storage
    assert "get_enabled_ddx_filters" in storage
    runtime = read("app/plugins/tigrao_fsm/runtime/ddx_runtime.py")
    assert "TIGRAO_FSM_DDX_HARD_ENABLED" in runtime
    assert "get_bot_permissions" in runtime
    assert "storage.get_enabled_ddx_filters" in runtime
    assert "delete_message" in runtime


def test_reactions_are_not_implemented_as_unchecked_hack() -> None:
    plugin_text = "\n".join(read(str(p.relative_to(ROOT))) for p in (ROOT / "app/plugins/tigrao_fsm").rglob("*.py"))
    assert "delete_message_reaction" not in plugin_text
    assert "delete_all_message_reactions" not in plugin_text
    assert "Reações ainda não implementadas" in plugin_text


def test_forbidden_music_files_do_not_reference_tigrao() -> None:
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


def test_app_bot_telegram_not_touched_for_tigrao() -> None:
    assert "tigrao_fsm" not in read("app/bot/telegram.py").lower()


def test_tigrao_text_handler_only_matches_waiting_dm() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    assert "class TigraoWaitingTextFilter" in panel
    assert "@router.message(TigraoWaitingTextFilter(), F.text)" in panel
    assert "@router.message(F.text)" not in panel
    assert "session is not None and session.waiting_for" in panel


def test_confirm_revalidates_destructive_flag_and_target_admin() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    assert "if not TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED" in panel
    assert "_target_admin_status" in panel
    assert "bot.get_chat_member(chat_id, int(user_id))" in panel
    assert "target_is_admin=target_is_admin" in panel
