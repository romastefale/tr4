from __future__ import annotations

from datetime import timedelta

from app.security.radio_templates import (
    create_template,
    delete_template,
    find_recent_duplicate,
    list_post_history,
    list_templates,
    message_hash,
    record_post_history,
    utcnow,
)


def test_template_lifecycle():
    template_id = create_template(name="Aviso", body="Texto do aviso", created_by_user_id=1)

    templates = list_templates()
    assert any(int(row["id"]) == template_id for row in templates)

    assert delete_template(template_id) is True
    assert delete_template(template_id) is False


def test_post_history_and_dedupe():
    h = message_hash("conteúdo")
    assert find_recent_duplicate(chat_id=-1001, message_hash_value=h) is None

    event_id = record_post_history(
        actor_user_id=1,
        chat_id=-1001,
        kind="text",
        message_hash_value=h,
        status="success",
    )

    duplicate = find_recent_duplicate(chat_id=-1001, message_hash_value=h)
    assert duplicate is not None
    assert duplicate["event_id"] == event_id

    history = list_post_history(chat_id=-1001)
    assert any(row["event_id"] == event_id for row in history)


def test_failed_history_does_not_count_as_duplicate():
    h = message_hash("falha")
    record_post_history(
        actor_user_id=1,
        chat_id=-1002,
        kind="text",
        message_hash_value=h,
        status="error",
    )
    assert find_recent_duplicate(chat_id=-1002, message_hash_value=h) is None
