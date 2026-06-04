from __future__ import annotations

from datetime import timedelta

from app.security.radio_drafts import (
    create_media_draft,
    create_text_draft,
    get_draft,
    is_draft_expired,
    mark_cancelled,
    mark_sent,
    purge_expired,
    utcnow,
)


def test_text_draft_lifecycle():
    draft_id = create_text_draft(
        actor_user_id=1,
        target_chat_id=-1001,
        text_value="hello",
        pin=True,
    )
    draft = get_draft(draft_id)
    assert draft is not None
    assert draft["kind"] == "text"
    assert draft["text"] == "hello"
    assert int(draft["pin"]) == 1
    assert draft["status"] == "pending"

    mark_sent(draft_id, sent_message_id=55)
    draft = get_draft(draft_id)
    assert draft["status"] == "sent"
    assert int(draft["sent_message_id"]) == 55


def test_media_draft_cancel_and_expiry():
    draft_id = create_media_draft(
        actor_user_id=1,
        target_chat_id=-1001,
        source_chat_id=1,
        source_message_id=10,
        pin=False,
        ttl_seconds=1,
    )
    draft = get_draft(draft_id)
    assert draft is not None
    assert draft["kind"] == "media"
    assert int(draft["source_message_id"]) == 10
    assert is_draft_expired(draft, now=utcnow() + timedelta(seconds=2)) is True

    mark_cancelled(draft_id)
    assert get_draft(draft_id)["status"] == "cancelled"
    assert purge_expired(now=utcnow() + timedelta(hours=1)) >= 0
