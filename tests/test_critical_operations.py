from __future__ import annotations

from app.security.critical_operations import (
    begin_critical_operation,
    critical_operations_summary,
    finish_critical_operation,
    get_critical_operation,
    list_critical_operations,
    replay_packet,
)


def test_critical_operation_lifecycle():
    operation_id = begin_critical_operation(
        category="governance",
        action="governance_set_title",
        operation_key="governance:-1001:title",
        actor_user_id=1,
        chat_id=-1001,
        lock_name="governance:-1001:governance_set_title",
        intent={"title": "Novo Nome"},
    )
    row = get_critical_operation(operation_id)
    assert row is not None
    assert row["status"] == "intent"
    assert row["intent"]["title"] == "Novo Nome"

    assert finish_critical_operation(operation_id, status="success", result={"ok": True}) is True
    row = get_critical_operation(operation_id)
    assert row is not None
    assert row["status"] == "success"
    assert row["result"]["ok"] is True


def test_critical_operations_summary_and_replay_packet():
    operation_id = begin_critical_operation(
        category="security",
        action="set_security_mode",
        operation_key="security_mode:alert",
        actor_user_id=1,
        intent={"mode": "alert"},
    )
    finish_critical_operation(operation_id, status="blocked", reason="operational_lock_busy")
    summary = critical_operations_summary(limit=10)
    assert summary["total_recent"] >= 1
    assert any(row["operation_id"] == operation_id for row in list_critical_operations(limit=10))
    packet = replay_packet(operation_id)
    assert "Replay automático não executado" in packet
    assert operation_id in packet
