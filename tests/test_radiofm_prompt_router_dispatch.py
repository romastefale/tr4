from __future__ import annotations

from types import SimpleNamespace

from aiogram.dispatcher.event.bases import UNHANDLED

from app.bot import radiofm
from app.bot import telegram


def _msg(chat_id=10, user_id=20, message_id=32, text="asa branca", reply_to=None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=user_id, full_name="Piero Fama"),
        message_id=message_id,
        text=text,
        reply_to_message=reply_to,
    )


def test_text_alias_defers_radiofm_prompt_reply_even_when_text_looks_like_play():
    radiofm._prompt_pending.clear()
    radiofm._prompt_pending[(10, 20)] = radiofm._PromptPending(
        user_id=20,
        chat_id=10,
        command_msg_id=29,
        prompt_msg_id=31,
    )
    message = _msg(text="toca asa branca", reply_to=SimpleNamespace(message_id=31))

    assert telegram._radiofm_prompt_pending(message) is True
    assert telegram._should_handle_text_alias(message) is False


def test_text_alias_returns_unhandled_for_non_play_text_so_subrouters_can_run():
    radiofm._prompt_pending.clear()
    message = _msg(text="asa branca")

    assert telegram._should_handle_text_alias(message) is False
