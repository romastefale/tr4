from __future__ import annotations

from app.bot import monthfm, music_extras, radiofm, tstory, weekfm


class _CardData:
    period_value = "JUNHO 2026"


def test_albnow_mentions_author_like_playing():
    caption = music_extras._format_albnow(
        "Piero Fama",
        8505890439,
        {
            "album_name": "Caju",
            "artist": "Liniker",
            "track_name": "Caju",
            "spotify_url": "https://open.spotify.com/album/abc",
        },
    )
    assert '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>' in caption


def test_week_month_mentions_author_like_playing():
    assert '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>' in weekfm._caption(_CardData(), "Piero Fama", 8505890439)
    assert '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>' in monthfm._format_caption(_CardData(), None, "Piero Fama", 8505890439)


def test_tstory_mentions_author_like_playing():
    caption = tstory._caption("Piero Fama", 8505890439, "Caju", "Liniker", "https://open.spotify.com/track/abc")
    assert '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>' in caption


def test_radiofm_uses_same_author_link_helper():
    assert radiofm._user_anchor(8505890439, "Piero Fama") == '<b><a href="tg://user?id=8505890439">Piero Fama</a></b>'
