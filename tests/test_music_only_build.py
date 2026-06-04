from __future__ import annotations

import pytest

pytest.importorskip("aiogram")

from app.bot.setup_commands import command_scope_summary
from app.security.rate_limit import check_command_rate_limit, reset_rate_limits


def test_public_commands_do_not_expose_moderation():
    summary = command_scope_summary()
    assert "playing" in summary["public"]
    assert "tigrao" not in summary["public"]
    assert "owner" not in summary["public"]
    assert "radio" not in summary["public"]


def test_rate_limit_basic():
    reset_rate_limits()
    assert check_command_rate_limit("playing", 10, -100).allowed

def test_phase0_legacy_moderation_residue_removed():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    forbidden_files = [
        "app/models/reaction_audit.py",
        "app/services/reaction_audit.py",
        "app/models/new_member_watch.py",
        "app/services/new_member_watch.py",
        "app/bot/filters.py",
    ]
    for rel in forbidden_files:
        assert not (root / rel).exists(), rel

    settings = (root / "app/config/settings.py").read_text()
    for token in (
        "TR3_SECURITY_",
        "TR3_AUDIT_",
        "TR3_PANIC_",
        "TR3_MANAGED_GROUP_IDS",
        "TR3_OPERATIONAL_LOCK_TTL_SECONDS",
        "TR3_SECOND_MODERATOR_ID",
        "TR3_THIRD_MODERATOR_ID",
        "MODERATOR_IDS",
    ):
        assert token not in settings

    telegram = (root / "app/bot/telegram.py").read_text()
    music_extras = (root / "app/bot/music_extras.py").read_text()
    database = (root / "app/db/database.py").read_text()

    for token in (
        'Command("hidden")',
        'Command("manual")',
        'F.users_shared',
        'reaction_audit',
        'new_member_watch',
    ):
        assert token not in telegram

    for token in ('Command("kingplay")', 'Command("debuguser")', 'kingplay:'):
        assert token not in music_extras

    assert "reaction_audit" not in database
    assert "new_member_watch" not in database

