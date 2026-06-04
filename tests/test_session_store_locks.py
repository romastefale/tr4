from __future__ import annotations

from app.security.session_store import (
    acquire_operational_lock,
    delete_private_session,
    list_operational_locks,
    list_private_sessions,
    load_private_session,
    release_operational_lock,
    save_private_session,
)


def test_private_session_roundtrip():
    save_private_session(namespace="test", user_id=1, payload={"selected_chat_id": -1001})
    payload = load_private_session(namespace="test", user_id=1)
    assert payload is not None
    assert payload["selected_chat_id"] == -1001
    assert any(row["namespace"] == "test" for row in list_private_sessions(namespace="test"))
    assert delete_private_session(namespace="test", user_id=1) is True


def test_operational_lock_acquire_conflict_release():
    first = acquire_operational_lock("test.lock", ttl_seconds=30, metadata={"kind": "unit"})
    assert first.acquired is True
    second = acquire_operational_lock("test.lock", ttl_seconds=30)
    assert second.acquired is False
    assert any(row["lock_name"] == "test.lock" for row in list_operational_locks())
    assert release_operational_lock("test.lock", owner=first.owner) is True
    third = acquire_operational_lock("test.lock", ttl_seconds=30)
    assert third.acquired is True
    assert release_operational_lock("test.lock", owner=third.owner) is True
