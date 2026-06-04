from __future__ import annotations

from datetime import datetime, timezone

from app.security.radio_schedules import (
    create_schedule,
    due_schedules,
    format_utc_offset,
    get_group_policy,
    is_quiet_now,
    list_schedules,
    parse_utc_offset_minutes,
    set_group_policy,
)
from app.security.radio_templates import create_template


def test_quiet_policy_roundtrip_and_offset():
    offset = parse_utc_offset_minutes("-03:00")
    assert offset == -180
    assert format_utc_offset(offset) == "-03:00"

    set_group_policy(
        chat_id=-1001,
        quiet_from="23:00",
        quiet_to="08:00",
        utc_offset_minutes=offset,
        updated_by_user_id=1,
    )

    policy = get_group_policy(-1001)
    assert policy is not None
    assert policy["quiet_from"] == "23:00"
    assert policy["quiet_to"] == "08:00"

    # 03:00 UTC = 00:00 local with -03:00 offset, inside quiet hours.
    assert is_quiet_now(-1001, now=datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)) is True


def test_schedule_lifecycle_and_due_query():
    template_id = create_template(name="agenda", body="conteúdo agendado", created_by_user_id=1)
    schedule_id = create_schedule(
        template_id=template_id,
        chat_id=-1002,
        interval_seconds=60,
        created_by_user_id=1,
        start_after_seconds=0,
    )

    schedules = list_schedules(chat_id=-1002)
    assert any(int(row["id"]) == schedule_id for row in schedules)

    due = due_schedules(now=datetime.now(timezone.utc), limit=10)
    assert any(int(row["id"]) == schedule_id for row in due)
