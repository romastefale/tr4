from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")
TRACK_SEARCH = (ROOT / "app" / "services" / "track_search.py").read_text(encoding="utf-8")


def test_empty_menu_path_still_present() -> None:
    assert "_INLINE_MENU_KINDS" in INLINE
    assert 'for item_kind in _INLINE_MENU_KINDS' in INLINE
    assert '"playing"' in INLINE and '"tly"' in INLINE and '"tcanvas"' in INLINE


def test_owner_free_text_claimed_by_v2() -> None:
    assert "owner: bool = False" in INLINE
    assert "owner=_is_owner(query.from_user.id)" in INLINE
    assert 'result_kind="pick"' in INLINE


def test_tly_prefix_search_uses_lyrics_flow_and_label() -> None:
    assert 'result_kind="tly"' in INLINE
    assert "(Lyrics)" in INLINE
    assert "_KIND_LOADING[\"tly\"]" in INLINE or "_KIND_LOADING['tly']" in INLINE
    assert "_render_tly" in INLINE
    assert "_pick_search_term" in INLINE


def test_manual_pick_has_symbol_without_count() -> None:
    assert "def _format_inline_manual_header" in INLINE
    assert "sem contador" in INLINE or "no play count" in INLINE
    assert "_render_pick" in INLINE


def test_search_still_edits_via_chosen_inline() -> None:
    assert "_edit_inline_rendered" in INLINE
    assert "chosen_inline_result" in INLINE
    assert "search_tracks" in INLINE


def test_track_search_exposes_album() -> None:
    assert "album: str | None = None" in TRACK_SEARCH
    assert "album_title" in TRACK_SEARCH
