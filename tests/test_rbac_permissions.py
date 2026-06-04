from __future__ import annotations

from sqlalchemy import text

from app.db.database import engine
from app.security import permissions as rbac


def _clear_grants() -> None:
    rbac.ensure_tables()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM moderation_grants"))


def test_root_has_all_permissions_without_grants():
    _clear_grants()
    assert rbac.has_permission(1, -1001, "moderation.ban") is True
    assert rbac.has_permission(1, -1001, "group.admins.promote") is True


def test_user_needs_chat_scoped_grant():
    _clear_grants()
    rbac.grant_permission(
        user_id=42,
        chat_id=-1001,
        permission="moderation.delete",
        granted_by_user_id=1,
    )
    assert rbac.has_permission(42, -1001, "moderation.delete") is True
    assert rbac.has_permission(42, -1002, "moderation.delete") is False
    assert rbac.has_permission(42, -1001, "moderation.ban") is False


def test_owner_only_permissions_are_not_delegable():
    _clear_grants()
    try:
        rbac.grant_permission(
            user_id=42,
            chat_id=-1001,
            permission="group.admins.promote",
            granted_by_user_id=1,
        )
    except rbac.OwnerOnlyError:
        pass
    else:
        raise AssertionError("grant_permission must reject Owner-only permissions")
    assert rbac.has_permission(42, -1001, "group.admins.promote") is False


def test_current_actor_guard():
    _clear_grants()
    rbac.grant_permission(
        user_id=42,
        chat_id=-1001,
        permission="moderation.delete",
        granted_by_user_id=1,
    )
    rbac.set_current_actor(42)
    rbac.require_current_actor_permission(-1001, "moderation.delete")
    try:
        rbac.require_current_actor_permission(-1001, "moderation.ban")
    except rbac.PermissionDeniedError:
        pass
    else:
        raise AssertionError("permission guard should deny missing grant")


def test_grant_permissions_rejects_owner_only_bundle():
    _clear_grants()
    try:
        rbac.grant_permissions(
            user_id=42,
            chat_id=-1001,
            permissions=("group.admins.promote",),
            granted_by_user_id=1,
        )
    except rbac.OwnerOnlyError:
        pass
    else:
        raise AssertionError("grant_permissions must reject Owner-only permissions")
