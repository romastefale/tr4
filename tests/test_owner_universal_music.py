from __future__ import annotations

from pathlib import Path


def test_code_owner_ids_gate(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "CODE_OWNER_IDS", frozenset({123456, 987654}))

    assert settings.is_code_owner(123456)
    assert settings.is_code_owner("987654")
    assert not settings.is_code_owner(111111)
    assert not settings.is_code_owner(None)


def test_owner_universal_routes_are_registered():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/public/tnow-universal" in paths
    assert "/api/public/songcharts-universal" in paths


def test_player_has_owner_only_universal_buttons():
    html = Path("app/web_music/player.html").read_text(encoding="utf-8")

    assert "tnowAllBtn" in html
    assert "/api/public/tnow-universal" in html
    assert "songchartsAllWeekBtn" in html
    assert "songchartsAllMonthBtn" in html
