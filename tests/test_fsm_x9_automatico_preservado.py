from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_preserves_automatic_ddx_after_contextual_x9() -> None:
    main = read("app/main.py")
    assert "from app.fsm_tigrao.x9 import record_x9_update_context" in main
    assert "from app.equalizador.ddx import equalizador_ddx_preprocess_update" in main
    assert "X9 de contexto apenas alimenta o FSM privado" in main
    assert "X9/DDX automático continua independente" in main
    x9_pos = main.index("record_x9_update_context(update)")
    ddx_pos = main.index("equalizador_ddx_preprocess_update(bot, update")
    dispatch_pos = main.index("dispatcher.feed_update(bot, update)")
    assert x9_pos < ddx_pos < dispatch_pos


def test_contextual_x9_documentation_does_not_turn_ddx_passive() -> None:
    x9 = read("app/fsm_tigrao/x9.py")
    context = read("app/fsm_tigrao/context.py")
    assert "this function is only the *contextual X9*" in x9
    assert "automatic X9/DDX pipeline remains in app.equalizador.ddx" in x9
    assert "auto-delete, event logging" in x9
    assert "automatic DDX/X9 is separate" in context
    assert "must not be used as the policy engine for automatic DDX" in context


def test_ddx_pipeline_still_contains_automatic_action_paths() -> None:
    ddx = read("app/equalizador/ddx.py")
    assert "async def equalizador_ddx_preprocess_update" in ddx
    assert "should not continue to regular bot handlers" in ddx
    assert "await _notify_maestros" in ddx
    assert "await bot.delete_message" in ddx or "delete_message(" in ddx
    assert "_record_event" in ddx


def test_private_fsm_group_commands_still_do_not_show_group_actions() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert "async def _silent_group_capture" in router
    assert "Contexto capturado pelo X9" in router
    silent = router.split("async def _silent_group_capture", 1)[1].split("def _is_private_waiting_ddx", 1)[0]
    assert "reply_markup" not in silent
    assert "mod_action_keyboard" not in silent
