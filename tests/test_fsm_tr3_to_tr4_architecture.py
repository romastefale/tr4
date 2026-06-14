from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_webapp_root_is_player_only() -> None:
    router = read("app/equalizador/router.py")
    assert "Web App é player musical" in router
    assert "return _equalizador_html_response(_PUBLIC_MUSIC_HTML)" in router


def test_contextual_fsm_router_registered() -> None:
    main = read("app/main.py")
    assert "fsm_tigrao_router" in main
    assert "dispatcher.include_router(fsm_tigrao_router)" in main


def test_private_commands_are_registered() -> None:
    setup = read("app/bot/setup_commands.py")
    private_block = setup.split("_PRIVATE_COMMANDS", 1)[1]
    for command in ("tmod", "tgrp", "tadd", "tdel", "town", "tctl", "tbrd"):
        assert f'CommandDef("{command}"' in private_block
    for legacy in ("mod", "grupo", "ddxadd", "ddxdel", "owner", "show", "broadcast"):
        assert f'CommandDef("{legacy}"' not in private_block


def test_mod_uses_private_x9_not_group_menu() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert '@router.message(Command("tmod", "mod"))' in router
    assert "_silent_group_capture" in router
    assert "chat_is_private(message.chat)" in router
    assert "list_recent_messages" in router
    assert "digite o id do grupo" not in router.lower()


def test_owner_aliases_show() -> None:
    show = read("app/bot/show_owner.py")
    assert '@router.message(Command("town", "tctl", "show", "owner"))' in show
