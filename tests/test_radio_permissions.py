from __future__ import annotations

import pytest

from app.security.permissions import (
    PermissionDeniedError,
    delegable_full_permissions,
    grant_permission,
    grant_permissions,
    has_any_radio_permission,
    has_permission,
    radio_full_permissions,
)


def test_radio_permissions_are_delegable_by_group():
    assert "radio.post_text" in radio_full_permissions()
    assert "radio.broadcast" in delegable_full_permissions()

    grant_permission(user_id=7001, chat_id=-1001, permission="radio.post_text", granted_by_user_id=1)
    assert has_permission(7001, -1001, "radio.post_text") is True
    assert has_permission(7001, -1002, "radio.post_text") is False
    assert has_any_radio_permission(7001) is True


def test_radio_permission_package_can_be_granted():
    grant_permissions(
        user_id=7002,
        chat_id=-1001,
        permissions=("radio.templates.use", "radio.history.read"),
        granted_by_user_id=1,
    )
    assert has_permission(7002, -1001, "radio.templates.use") is True
    assert has_permission(7002, -1001, "radio.history.read") is True


def test_unknown_radio_permission_is_rejected():
    with pytest.raises(PermissionDeniedError):
        grant_permission(user_id=7003, chat_id=-1001, permission="radio.root", granted_by_user_id=1)
