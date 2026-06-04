from __future__ import annotations

from app.security.session_store import acquire_operational_lock, release_operational_lock


def test_operational_lock_blocks_duplicate_critical_action():
    first = acquire_operational_lock("test_critical_action", ttl_seconds=5, metadata={"action": "test"})
    assert first.acquired is True

    second = acquire_operational_lock("test_critical_action", ttl_seconds=5)
    assert second.acquired is False
    assert second.owner == first.owner

    assert release_operational_lock("test_critical_action", owner=first.owner) is True


def test_operational_lock_can_be_reacquired_after_release():
    first = acquire_operational_lock("test_critical_reacquire", ttl_seconds=5)
    assert first.acquired is True
    assert release_operational_lock("test_critical_reacquire", owner=first.owner) is True

    second = acquire_operational_lock("test_critical_reacquire", ttl_seconds=5)
    assert second.acquired is True
    assert release_operational_lock("test_critical_reacquire", owner=second.owner) is True
