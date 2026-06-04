from __future__ import annotations

from app.security.audit import ensure_tables, list_recent_events, log_audit_event


def test_audit_event_roundtrip():
    ensure_tables()
    event_id = log_audit_event(
        category="test",
        action="governance_confirm",
        status="success",
        actor_user_id=1,
        chat_id=-100,
        payload={"x": 1},
    )
    rows = list_recent_events(category="test")
    assert any(row["event_id"] == event_id for row in rows)
