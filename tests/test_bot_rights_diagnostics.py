from __future__ import annotations

from app.security.bot_rights import (
    BotRights,
    bot_rights_capabilities,
    bot_rights_payload,
    format_bot_rights,
    format_rights_refresh_report,
    refresh_managed_group_rights,
)


def test_bot_rights_capabilities_for_admin():
    rights = BotRights(
        chat_id=-1001,
        status="administrator",
        is_admin=True,
        can_delete_messages=True,
        can_restrict_members=True,
        can_pin_messages=False,
        can_invite_users=True,
    )
    assert bot_rights_capabilities(rights) == {"admin", "delete", "restrict", "invite"}


def test_bot_rights_capabilities_for_non_admin():
    rights = BotRights(chat_id=-1001, status="member", is_admin=False)
    assert bot_rights_capabilities(rights) == set()


def test_bot_rights_payload_is_serializable_shape():
    rights = BotRights(chat_id=-1001, status="administrator", is_admin=True, can_pin_messages=True)
    payload = bot_rights_payload(rights)
    assert payload["chat_id"] == -1001
    assert payload["is_admin"] is True
    assert "pin" in payload["capabilities"]


def test_format_bot_rights_reports_musical_only():
    rights = BotRights(chat_id=-1001, status="member", is_admin=False)
    assert "musical-only" in format_bot_rights(rights)


def test_format_rights_refresh_report():
    report = format_rights_refresh_report(
        {
            "total": 2,
            "admin": 1,
            "musical_only": 1,
            "error": 0,
            "rows": [
                {"chat_id": -1001, "is_admin": True, "capabilities": ["admin", "pin", "delete"]},
                {"chat_id": -1002, "is_admin": False, "status": "member"},
            ],
        }
    )
    assert "Total: 2" in report
    assert "-1001" in report
    assert "musical-only" in report


def test_refresh_managed_group_rights_callable():
    assert callable(refresh_managed_group_rights)
