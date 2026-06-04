from __future__ import annotations

from app.bot.setup_commands import private_command_names_for_access, sync_active_grant_command_scopes
from app.security.permissions import grant_permission, list_active_grant_user_ids


def test_list_active_grant_user_ids_includes_radio_delegate():
    grant_permission(user_id=8001, chat_id=-1001, permission="radio.post_text", granted_by_user_id=1)
    assert 8001 in list_active_grant_user_ids()


def test_resync_helper_is_callable():
    assert callable(sync_active_grant_command_scopes)


def test_resync_command_selection_keeps_moderation_only_without_radio():
    commands = private_command_names_for_access(is_root=False, has_delegate_access=True, has_radio_access=False)
    assert "tigrao" in commands
    assert "radio" not in commands
    assert "owner" not in commands
