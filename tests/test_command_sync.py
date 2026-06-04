from __future__ import annotations

from app.bot.setup_commands import private_command_names_for_access


def test_private_command_names_for_owner():
    commands = private_command_names_for_access(is_root=True, has_delegate_access=False, has_radio_access=False)
    assert "tigrao" in commands
    assert "owner" in commands
    assert "radio" in commands


def test_private_command_names_for_delegate():
    commands = private_command_names_for_access(is_root=False, has_delegate_access=True, has_radio_access=True)
    assert "tigrao" in commands
    assert "radio" in commands
    assert "owner" not in commands


def test_private_command_names_without_access_falls_back_to_public():
    commands = private_command_names_for_access(is_root=False, has_delegate_access=False, has_radio_access=False)
    assert "playing" in commands
    assert "tigrao" not in commands
    assert "owner" not in commands
    assert "radio" not in commands


def test_private_command_names_for_moderation_only_delegate():
    commands = private_command_names_for_access(is_root=False, has_delegate_access=True, has_radio_access=False)
    assert "tigrao" in commands
    assert "radio" not in commands
    assert "owner" not in commands
