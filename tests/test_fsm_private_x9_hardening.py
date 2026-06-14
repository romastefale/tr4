from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_x9_has_retention_limits_and_does_not_learn_unknown_groups_by_default() -> None:
    settings = read("app/config/settings.py")
    context = read("app/fsm_tigrao/context.py")
    x9 = read("app/fsm_tigrao/x9.py")
    assert "TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS" in settings
    assert "False" in settings.split("TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS", 1)[1].splitlines()[0]
    assert "def x9_group_capture_allowed" in context
    assert "TR4_EQUALIZADOR_PALCO_IDS_SET" in context
    assert "TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS" in context
    assert "allow_unknown_group=False" in x9


def test_x9_context_is_pruned_by_age_and_count() -> None:
    context = read("app/fsm_tigrao/context.py")
    assert "def prune_x9_context" in context
    assert "TR4_FSM_X9_MESSAGE_TTL_SECONDS" in context
    assert "TR4_FSM_X9_MAX_MESSAGES_PER_GROUP" in context
    assert "telegram_message_date < :cutoff" in context
    assert "LIMIT :limit" in context
    assert "prune_x9_context(chat_id=int(chat_id), db_engine=db_engine)" in context


def test_group_trigger_does_not_send_msg_ref_before_authorization() -> None:
    router = read("app/fsm_tigrao/router.py")
    silent = router.split("async def _silent_group_capture", 1)[1].split("def _is_private_waiting_ddx", 1)[0]
    assert "configured_actor = _private_allowed(user_id)" in silent
    assert "if configured_actor:" in silent
    assert "allow_unknown_group=True" in silent
    assert "Referência:" not in silent
    assert "msg_ref" not in silent
    assert "message.bot.send_message" in silent


def test_private_mod_tokens_are_bound_to_user_and_action() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert "def _new_token(payload: dict[str, Any], *, user_id: int)" in router
    assert 'payload["user_id"] = int(user_id)' in router
    assert "def _token_payload(token: str, *, user_id: int | None = None)" in router
    assert "int(payload.get(\"user_id\") or 0) != int(user_id)" in router
    assert "data[\"pending_action\"] = action" in router
    assert "str(data.get(\"pending_action\") or \"\") != action" in router


def test_recent_message_listing_uses_operational_window_only() -> None:
    context = read("app/fsm_tigrao/context.py")
    assert "m.telegram_message_date IS NOT NULL" in context
    assert "m.telegram_message_date >= :cutoff" in context
    assert "def get_message_by_ref" in context
