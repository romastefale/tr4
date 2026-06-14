from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
SPOTIFY = (ROOT / "app" / "services" / "spotify.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app" / "templates" / "tnow_card.html").read_text(encoding="utf-8")


def test_tnow_aceita_recentes_ate_30_minutos():
    assert "TNOW_RECENT_YELLOW_MINUTES = 15" in TNOW
    assert "TNOW_RECENT_RED_MINUTES = 30" in TNOW
    assert '"recent_15"' in TNOW
    assert '"recent_30"' in TNOW
    assert '"stale"' in TNOW
    assert "_classify_tnow_track" in TNOW
    assert "spotify_last" in TNOW
    assert "lastfm_last" in TNOW


def test_tnow_preenche_grade_com_antigos_cinza():
    assert "_grid_slots" in TNOW
    assert "missing = min(_grid_slots(len(selected)) - len(selected)" in TNOW
    assert "selected.extend(stale[:missing])" in TNOW


def test_spotify_pausado_tem_timestamp_para_recentes():
    assert 'mapped["player_timestamp_ms"] = timestamp_ms' in SPOTIFY
    assert 'mapped["played_at"] = datetime.fromtimestamp(' in SPOTIFY


def test_card_tem_status_visual_colorido_top_right():
    assert "status: str = \"live\"" in CARD
    assert "age_minutes: int | None = None" in CARD
    assert "status-dot" in CARD
    assert "status-live" in TEMPLATE
    assert "status-recent-15" in TEMPLATE
    assert "status-recent-30" in TEMPLATE
    assert "status-stale" in TEMPLATE
    assert "right: 12px" in TEMPLATE
    assert "#3FE0A6" in TEMPLATE
