from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")


def test_phase40_message_link_parser_accepts_common_private_formats() -> None:
    from app.equalizador.mesa import parse_telegram_message_link

    aliases = {"radio": -1003818494866}
    assert parse_telegram_message_link(
        link="https://t.me/c/3818494866/123",
        aliases=aliases,
        expected_chat_id=-1003818494866,
    ) == (-1003818494866, 123)
    assert parse_telegram_message_link(
        link="https://t.me/c/3818494866/45/123?thread=45",
        aliases=aliases,
        expected_chat_id=-1003818494866,
    ) == (-1003818494866, 123)
    assert parse_telegram_message_link(
        link="tg://privatepost?channel=3818494866&post=123",
        aliases=aliases,
        expected_chat_id=-1003818494866,
    ) == (-1003818494866, 123)


def test_phase40_message_link_parser_accepts_alias_and_raw_message_id() -> None:
    from app.equalizador.mesa import parse_telegram_message_link

    aliases = {"radio": -1003818494866}
    assert parse_telegram_message_link(
        link="https://t.me/radio/987",
        aliases=aliases,
        expected_chat_id=-1003818494866,
    ) == (-1003818494866, 987)
    assert parse_telegram_message_link(
        link="987",
        aliases=aliases,
        expected_chat_id=-1003818494866,
    ) == (-1003818494866, 987)


def test_phase40_message_link_parser_rejects_other_palco() -> None:
    from app.equalizador.mesa import MesaTargetError, parse_telegram_message_link

    with pytest.raises(MesaTargetError, match="outro palco"):
        parse_telegram_message_link(
            link="https://t.me/c/2556760909/123",
            aliases={"geeks": -1002556760909},
            expected_chat_id=-1003818494866,
        )


def test_phase40_manual_target_normalization_is_present() -> None:
    text = Path("app/equalizador/mesa.py").read_text()
    assert "def _normalize_manual_target_input" in text
    assert "tg://user" not in text
    assert "link t.me/username" in text
    assert 'raw.startswith("usr_")' in text
