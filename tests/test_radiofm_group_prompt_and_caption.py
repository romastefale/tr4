from __future__ import annotations

from types import SimpleNamespace

from app.bot import radiofm
from app.services.track_search import TrackHit


def _msg(chat_id=10, user_id=20, message_id=30, text="Caju", reply_to=None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=user_id, full_name="Piero Fama"),
        message_id=message_id,
        text=text,
        reply_to_message=reply_to,
    )


def test_radiofm_caption_uses_playing_author_format_and_spotify_link():
    hit = TrackHit(
        track_id="deezer:1",
        title="Caju",
        artist="Liniker",
        cover_big="https://deezer.example/cover.jpg",
        cover_thumb=None,
        url="https://www.deezer.com/track/1",
    )

    caption = radiofm._card_caption(
        hit,
        user_id=8505890439,
        user_name="Piero Fama",
        spotify_url="https://open.spotify.com/track/abc",
    )

    assert '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>' in caption
    assert '<a href="https://open.spotify.com/track/abc">Caju</a>' in caption
    assert "Liniker" in caption
    assert "deezer.com" not in caption
    assert "♥" not in caption
    assert "<code>" not in caption


def test_radiofm_prompt_accepts_reply_to_bot_question():
    radiofm._prompt_pending.clear()
    radiofm._prompt_pending[(10, 20)] = radiofm._PromptPending(
        user_id=20,
        chat_id=10,
        command_msg_id=29,
        prompt_msg_id=31,
    )
    answer = _msg(message_id=50, reply_to=SimpleNamespace(message_id=31))

    assert radiofm._is_radiofm_prompt_answer(answer) is True


def test_radiofm_prompt_accepts_next_message_from_same_author_only():
    radiofm._prompt_pending.clear()
    radiofm._prompt_pending[(10, 20)] = radiofm._PromptPending(
        user_id=20,
        chat_id=10,
        command_msg_id=29,
        prompt_msg_id=31,
    )

    assert radiofm._is_radiofm_prompt_answer(_msg(user_id=20, message_id=32)) is True
    assert radiofm._is_radiofm_prompt_answer(_msg(user_id=21, message_id=32)) is False
