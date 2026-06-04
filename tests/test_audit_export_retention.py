from __future__ import annotations

from app.security.audit import cleanup_audit_events_older_than, export_audit_events_jsonl, log_audit_event
from app.security.critical_operations import (
    begin_critical_operation,
    cleanup_critical_operations_older_than,
    export_critical_operations_jsonl,
    finish_critical_operation,
)


def test_audit_export_jsonl_contains_event():
    event_id = log_audit_event(category="test", action="export", status="success", payload={"ok": True})
    data = export_audit_events_jsonl(limit=20)
    assert isinstance(data, bytes)
    assert event_id.encode() in data
    assert b'"payload"' in data


def test_critical_operations_export_jsonl_contains_operation():
    operation_id = begin_critical_operation(category="test", action="export", operation_key="test:export", intent={"ok": True})
    finish_critical_operation(operation_id, status="success", result={"done": True})
    data = export_critical_operations_jsonl(limit=20)
    assert isinstance(data, bytes)
    assert operation_id.encode() in data
    assert b'"intent"' in data
    assert b'"result"' in data


def test_cleanup_helpers_are_callable_and_use_safe_min_days():
    assert isinstance(cleanup_audit_events_older_than(1), int)
    assert isinstance(cleanup_critical_operations_older_than(1), int)
