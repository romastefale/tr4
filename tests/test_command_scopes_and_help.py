from __future__ import annotations

from types import SimpleNamespace

from app.bot.setup_commands import command_scope_summary
from app.bot.telegram import _help_text, _start_text


class DummyUser(SimpleNamespace):
    pass


class DummyChat(SimpleNamespace):
    pass


def _msg(chat_type: str, user_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        chat=DummyChat(type=chat_type, title="Grupo Teste"),
        from_user=DummyUser(id=user_id, full_name="Piero"),
    )


def test_command_scopes_are_separated() -> None:
    summary = command_scope_summary()
    assert "login" in summary["private"]
    assert "logout" in summary["private"]
    assert "nowp" in summary["private"]
    assert "songcharts" not in summary["private"]
    assert "tnow" not in summary["private"]

    assert "radiofm" in summary["group"]
    assert "tnow" in summary["group"]
    assert "songcharts" in summary["group"]
    assert "login" not in summary["group"]
    assert "logout" not in summary["group"]
    assert "nowp" not in summary["group"]

    assert set(summary["owner_only"]).issubset(set(summary["owner_private"]))
    assert "tnowall" not in summary["private"]
    assert "tnowall" not in summary["group"]


def test_group_help_matches_group_scope() -> None:
    text = _help_text(_msg("supergroup"))
    assert "/radiofm" in text
    assert "/tnow" in text
    assert "/songcharts" in text
    assert "/login" not in text
    assert "/nowp" not in text
    assert "/tnowall" not in text


def test_private_help_matches_private_scope() -> None:
    text = _help_text(_msg("private"))
    assert "/login" in text
    assert "/nowp" in text
    assert "/radiofm" in text
    assert "/songcharts" not in text
    assert "/tnowall" not in text


def test_start_text_is_contextual() -> None:
    group_text = _start_text(_msg("supergroup"))
    private_text = _start_text(_msg("private"))
    assert "tigraoRADIO no grupo" in group_text
    assert "/songcharts" in group_text
    assert "Bem-vindo ao tigraoRADIO" in private_text
    assert "/login" in private_text
