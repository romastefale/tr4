from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_group_trigger_does_not_enroll_unknown_group_for_plain_chat_admin() -> None:
    router = read("app/fsm_tigrao/router.py")
    silent = router.split("async def _silent_group_capture", 1)[1].split("def _is_private_waiting_ddx", 1)[0]
    assert "configured_actor = _private_allowed(user_id)" in silent
    assert "user_can_operate_group" not in silent
    assert "allow_unknown_group=True" in silent
    assert "if configured_actor:" in silent
    assert "message.bot.send_message" in silent


def test_silent_trigger_still_has_no_group_menu_or_reference_leak() -> None:
    router = read("app/fsm_tigrao/router.py")
    silent = router.split("async def _silent_group_capture", 1)[1].split("def _is_private_waiting_ddx", 1)[0]
    assert "reply_markup" not in silent
    assert "mod_action_keyboard" not in silent
    assert "msg_ref" not in silent
    assert "Referência:" not in silent
    assert "await message.delete()" in silent
