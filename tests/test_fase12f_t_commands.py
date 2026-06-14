from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_private_menu_uses_t_prefixed_commands_only() -> None:
    setup = read("app/bot/setup_commands.py")
    public_block = setup.split("_PRIVATE_COMMANDS", 1)[0]
    private_block = setup.split("_PRIVATE_COMMANDS", 1)[1]
    for command in ("tmod", "tgrp", "town", "tctl", "tbrd", "tadd", "tdel"):
        assert f'CommandDef("{command}"' in private_block
        assert f'CommandDef("{command}"' not in public_block
    for legacy in ("mod", "grupo", "owner", "show", "broadcast", "ddxadd", "ddxdel"):
        assert f'CommandDef("{legacy}"' not in private_block
        assert f'CommandDef("{legacy}"' not in public_block


def test_handlers_keep_legacy_aliases_for_transition() -> None:
    router = read("app/fsm_tigrao/router.py")
    show = read("app/bot/show_owner.py")
    broadcast = read("app/bot/music_broadcast.py")
    assert '@router.message(Command("tmod", "mod"))' in router
    assert '@router.message(Command("tgrp", "grupo"))' in router
    assert '@router.message(Command("tadd", "tdel", "ddxadd", "ddxdel"))' in router
    assert '@router.message(Command("town", "tctl", "show", "owner"))' in show
    assert '@router.message(Command("tbrd", "broadcast"))' in broadcast


def test_user_facing_help_points_to_new_commands() -> None:
    router = read("app/fsm_tigrao/router.py")
    show = read("app/bot/show_owner.py")
    broadcast = read("app/bot/music_broadcast.py")
    assert "Abra /tmod aqui no privado" in router
    assert "Escolha um grupo primeiro com /tgrp" in router
    assert "envie /tadd e /tdel" in router
    assert "Use /town ou /tctl" in show
    assert "Use /tbrd no privado" in broadcast
