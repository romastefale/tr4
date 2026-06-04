from __future__ import annotations

from app.moderation_tigrao import state as tig_state
from app.moderation_tigrao.state import (
    clear_user_session,
    get_session,
    reset_current_user,
    set_action,
    set_current_user,
    set_selected_group,
)
from app.security.permissions import grant_permission


def test_tigrao_session_persists_selected_group_for_granted_user():
    user_id = 9101
    grant_permission(user_id=user_id, chat_id=-1001, permission="radio.post_text", granted_by_user_id=1)
    token = set_current_user(user_id)
    try:
        set_selected_group(-1001, "Grupo teste")
        set_action("radio_test", waiting_for="outbound_text", draft_id=123)
    finally:
        reset_current_user(token)
    tig_state._sessions.pop(user_id, None)
    token = set_current_user(user_id)
    try:
        session = get_session()
        assert session.selected_chat_id == -1001
        assert session.waiting_for == "outbound_text"
        assert session.payload["draft_id"] == 123
    finally:
        reset_current_user(token)
        clear_user_session(user_id)
