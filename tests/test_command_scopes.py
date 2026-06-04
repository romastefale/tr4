from __future__ import annotations

from app.bot.setup_commands import command_scope_summary


def test_public_scope_does_not_expose_sensitive_panels():
    summary = command_scope_summary()
    assert "playing" in summary["public"]
    assert "radiofm" in summary["public"]
    assert "tigrao" not in summary["public"]
    assert "owner" not in summary["public"]
    assert "radio" not in summary["public"]


def test_owner_scope_exposes_private_panels():
    summary = command_scope_summary()
    assert "tigrao" in summary["owner_private"]
    assert "owner" in summary["owner_private"]
    assert "radio" in summary["owner_private"]


def test_delegate_scope_has_entry_but_not_owner_panel():
    summary = command_scope_summary()
    assert "tigrao" in summary["delegate_private"]
    assert "radio" in summary["delegate_private"]
    assert "owner" not in summary["delegate_private"]
