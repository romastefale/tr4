from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.bot.telegram import _help_text, _start_text


class DummyUser(SimpleNamespace):
    pass


class DummyChat(SimpleNamespace):
    pass


def _msg(chat_type: str, user_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(chat=DummyChat(type=chat_type, title="Grupo"), from_user=DummyUser(id=user_id, full_name="Piero"))


def test_public_start_and_help_do_not_reference_hidden_scopes() -> None:
    text = "\n".join([
        _start_text(_msg("private")),
        _help_text(_msg("private")),
        _start_text(_msg("supergroup")),
        _help_text(_msg("supergroup")),
    ]).lower()
    forbidden = ["dono", "código", "codigo", "universal", "universais", "exclusivo", "exclusivos"]
    assert not any(word in text for word in forbidden)


def test_owner_start_and_help_use_neutral_wording(monkeypatch) -> None:
    import app.bot.telegram as telegram

    monkeypatch.setattr(telegram, "_is_owner_message", lambda message: True)
    text = "\n".join([telegram._start_text(_msg("private")), telegram._help_text(_msg("private"))]).lower()
    forbidden = ["dono", "código", "codigo", "universal", "universais", "exclusivo", "exclusivos"]
    assert not any(word in text for word in forbidden)
    assert "/tnowall" in text
    assert "consolidado" in text


def test_inline_playing_caption_matches_radiofm_visual_pattern() -> None:
    source = Path("app/bot/telegram.py").read_text(encoding="utf-8")
    assert 'caption = f"{who_part}\\n\\n♫ <b>{track_part}</b> — <i>{artist}</i>"' in source
    assert 'caption = f"{who_part} · <i>{track_part} - {artist}</i>"' not in source
