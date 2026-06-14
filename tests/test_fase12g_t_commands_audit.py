from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tadd_and_tdel_map_to_correct_ddx_branch() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert 'if command in {"tadd", "ddxadd"}:' in router
    assert 'elif command in {"tdel", "ddxdel"}:' in router
    assert 'Comando DDX inválido. Use /tadd ou /tdel no privado.' in router
    add_pos = router.index('if command in {"tadd", "ddxadd"}:')
    del_pos = router.index('elif command in {"tdel", "ddxdel"}:')
    assert add_pos < del_pos


def test_t_commands_remain_private_scope_only_and_legacy_only_aliases() -> None:
    setup = read("app/bot/setup_commands.py")
    public_block = setup.split("_PRIVATE_COMMANDS", 1)[0]
    private_block = setup.split("_PRIVATE_COMMANDS", 1)[1]
    for command in ("tmod", "tgrp", "town", "tctl", "tbrd", "tadd", "tdel"):
        assert f'CommandDef("{command}"' in private_block
        assert f'CommandDef("{command}"' not in public_block
    for legacy in ("mod", "grupo", "owner", "show", "broadcast", "ddxadd", "ddxdel"):
        assert f'CommandDef("{legacy}"' not in private_block
        assert f'CommandDef("{legacy}"' not in public_block


def test_group_trigger_still_silent_after_t_command_rename() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert '@router.message(Command("tmod", "mod"))' in router
    assert '@router.message(Command("tgrp", "grupo"))' in router
    assert '@router.message(Command("tadd", "tdel", "ddxadd", "ddxdel"))' in router
    assert 'if chat_is_group(message.chat):\n        await _silent_group_capture(message)\n        return' in router
    assert 'reply_markup=mod_action_keyboard' in router
    assert 'chat_is_private(callback.message.chat)' in router
