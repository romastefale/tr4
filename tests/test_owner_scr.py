from __future__ import annotations

from app.bot.owner_scr import parse_play_count, parse_track_from_caption


def test_parse_playing_caption_with_play_count() -> None:
    caption = (
        '<b><a href="tg://user?id=1">PI</a></b>\n'
        '♫ <code>12</code> · <b><a href="https://open.spotify.com/track/x">Helix</a></b> — <i>Flume</i>'
    )
    parsed = parse_track_from_caption(caption)
    assert parsed == ("Helix", "Flume", None)


def test_parse_playing_caption_without_count() -> None:
    caption = "<b>PI</b>\n♫ <b>Helix</b> — <i>Flume</i>"
    parsed = parse_track_from_caption(caption)
    assert parsed == ("Helix", "Flume", None)


def test_parse_albnow_caption() -> None:
    caption = '<b><a href="tg://user?id=1">PI</a></b> · <i>♬ Helix — Flume</i>'
    parsed = parse_track_from_caption(caption)
    assert parsed == ("Helix", "Flume", None)


def test_parse_radiofm_caption() -> None:
    caption = "♫ Helix — Flume"
    parsed = parse_track_from_caption(caption)
    assert parsed == ("Helix", "Flume", None)


def test_parse_rejects_plain_text() -> None:
    assert parse_track_from_caption("oi") is None
    assert parse_track_from_caption("") is None


def test_parse_play_count_bounds() -> None:
    assert parse_play_count("123", max_plays=500) == 123
    assert parse_play_count("1", max_plays=500) == 1
    assert parse_play_count("0", max_plays=500) is None
    assert parse_play_count("501", max_plays=500) is None
    assert parse_play_count("12abc", max_plays=500) is None
    assert parse_play_count("", max_plays=500) is None
