from datetime import datetime

from app.services.tnow_card import TnowEntry, build_tnow_card_html


def test_build_tnow_card_html_uses_imported_timezone_without_unboundlocalerror():
    html = build_tnow_card_html([
        TnowEntry(
            user_id=1,
            display_name="Piero",
            track_name="Caju",
            artist="Liniker",
            cover_bytes=None,
            source="lastfm",
        )
    ], now=datetime(2026, 6, 14, 15, 12))
    assert "Piero" in html
    assert "Caju" in html
    assert "Liniker" in html
    assert "14/06" in html
