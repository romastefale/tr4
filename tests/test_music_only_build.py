from __future__ import annotations

from app.bot.setup_commands import command_scope_summary
from app.security.rate_limit import check_command_rate_limit, reset_rate_limits


def test_public_commands_are_music_only():
    summary = command_scope_summary()
    assert "playing" in summary["public"]
    assert "tigrao" not in summary["public"]
    assert "radio" not in summary["public"]


def test_rate_limit_basic():
    reset_rate_limits()
    assert check_command_rate_limit("playing", 10, -100).allowed
