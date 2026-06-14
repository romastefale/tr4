from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_group_commands_are_silent_capture_not_group_menu() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert "Fase 12B rule" in router
    assert "async def _silent_group_capture" in router
    assert "await _silent_group_capture(message)" in router
    assert "await message.reply" not in router
    assert "reply_markup=mod_action_keyboard" in router
    assert "chat_is_private(callback.message.chat)" in router
    assert "@router.message(F.text, _is_private_waiting_ddx)" in router


def test_x9_capture_runs_before_dispatch_without_intercepting_handlers() -> None:
    main = read("app/main.py")
    assert "from app.fsm_tigrao.x9 import record_x9_update_context" in main
    assert "record_x9_update_context(update)" in main
    assert "await dispatcher.feed_update(bot, update)" in main


def test_operational_commands_are_private_scope_only() -> None:
    setup = read("app/bot/setup_commands.py")
    public_block = setup.split("_PRIVATE_COMMANDS", 1)[0]
    private_block = setup.split("_PRIVATE_COMMANDS", 1)[1]
    for command in ("tmod", "tgrp", "tadd", "tdel", "town", "tctl", "tbrd"):
        assert f'CommandDef("{command}"' not in public_block
        assert f'CommandDef("{command}"' in private_block
    for legacy in ("mod", "grupo", "ddxadd", "ddxdel", "owner", "show", "broadcast"):
        assert f'CommandDef("{legacy}"' not in public_block
        assert f'CommandDef("{legacy}"' not in private_block


def test_private_fsm_lists_groups_and_recent_messages() -> None:
    context = read("app/fsm_tigrao/context.py")
    router = read("app/fsm_tigrao/router.py")
    assert "def list_known_groups" in context
    assert "def list_recent_messages" in context
    assert "def get_message_by_ref" in context
    assert "groups_keyboard(groups, prefix=\"pmod\")" in router
    assert "messages_keyboard(messages" in router


def test_webapp_root_remains_player_only() -> None:
    router = read("app/equalizador/router.py")
    assert "Web App é player musical" in router
    assert "return _equalizador_html_response(_PUBLIC_MUSIC_HTML)" in router
