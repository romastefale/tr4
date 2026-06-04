from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.moderation_tigrao import state as tig_state
from app.btb import state as btb_state
from app.security.permissions import get_current_actor, reset_current_actor, set_current_actor


def test_tigrao_context_token_reset_restores_previous_user():
    outer = tig_state.set_current_user(1001)
    try:
        assert tig_state.current_user_id() == 1001
        inner = tig_state.set_current_user(1002)
        try:
            assert tig_state.current_user_id() == 1002
        finally:
            tig_state.reset_current_user(inner)
        assert tig_state.current_user_id() == 1001
    finally:
        tig_state.reset_current_user(outer)
    assert tig_state.current_user_id() is None


def test_btb_context_token_reset_restores_previous_user():
    token = btb_state.set_current_user(2001)
    assert btb_state.current_user_id() == 2001
    btb_state.reset_current_user(token)
    assert btb_state.current_user_id() is None


def test_security_actor_token_reset():
    outer = set_current_actor(None)
    try:
        token = set_current_actor(3001)
        assert get_current_actor() == 3001
        reset_current_actor(token)
        assert get_current_actor() is None
    finally:
        reset_current_actor(outer)


def test_tigrao_cleanup_expired_sessions_removes_idle_sessions():
    tig_state._sessions.clear()
    token = tig_state.set_current_user(tig_state.OWNER_ID)
    try:
        session = tig_state.set_selected_group(-1001, "Grupo")
        session.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        assert tig_state.session_count() == 1
        removed = tig_state.cleanup_expired_sessions(max_idle_seconds=60)
        assert removed == 1
        assert tig_state.session_count() == 0
    finally:
        tig_state.reset_current_user(token)
        tig_state._sessions.clear()


def test_session_diagnostics_does_not_expose_payload_values():
    tig_state._sessions.clear()
    token = tig_state.set_current_user(tig_state.OWNER_ID)
    try:
        tig_state.set_action("secret", waiting_for="input", token="supersecret")
        diag = tig_state.session_diagnostics()
        row = diag["rows"][0]
        assert row["payload_keys"] == ["token"]
        assert "supersecret" not in str(diag)
    finally:
        tig_state.reset_current_user(token)
        tig_state._sessions.clear()
