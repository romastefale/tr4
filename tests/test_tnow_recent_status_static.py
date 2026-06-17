from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
SPOTIFY = (ROOT / "app" / "services" / "spotify.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app" / "templates" / "tnow_card.html").read_text(encoding="utf-8")
CACHE = (ROOT / "app" / "services" / "tnow_activity_cache.py").read_text(encoding="utf-8")
MODEL = (ROOT / "app" / "models" / "tnow_recent_track.py").read_text(encoding="utf-8")
DB = (ROOT / "app" / "db" / "database.py").read_text(encoding="utf-8")


def test_tnow_aceita_janelas_ate_2_horas():
    assert "TNOW_RECENT_YELLOW_MINUTES = 15" in TNOW
    assert "TNOW_RECENT_ORANGE_MINUTES = 30" in TNOW
    assert "TNOW_RECENT_RED_MINUTES = 45" in TNOW
    assert "TNOW_RECENT_GRAY_MINUTES = 120" in TNOW
    for status in ('"live"', '"recent_15"', '"recent_30"', '"recent_45"', '"recent_120"', '"expired"'):
        assert status in TNOW or status in CACHE
    assert "classify_recent_track" in TNOW
    assert "spotify_last" in TNOW
    assert "lastfm_last" in TNOW


def test_tnow_cache_persistente_guarda_user_lastfm_track_e_quando_ouviu():
    assert 'class TnowRecentTrack(Base)' in MODEL
    assert '__tablename__ = "tnow_recent_tracks"' in MODEL
    for field in (
        "user_id",
        "lastfm_username",
        "track_name",
        "artist",
        "played_at",
        "observed_at",
        "fetched_at",
        "expires_at",
        "raw_age_seconds",
    ):
        assert field in MODEL
    assert "CREATE TABLE IF NOT EXISTS tnow_recent_tracks" in DB
    assert "from app.models.tnow_recent_track import TnowRecentTrack" in DB
    assert "TNOW_CACHE_UPSERT" in CACHE
    assert "TNOW_ENTRY_DECISION" in TNOW


def test_tnow_grade_adaptativa_nao_corta_usuario_valido():
    assert "_TNOW_GRID_LAYOUTS" in TNOW
    for layout in ("(1, 1)", "(2, 3)", "(2, 4)", "(3, 5)", "(4, 5)", "(5, 5)"):
        assert layout in TNOW
    assert "_choose_grid_layout" in TNOW
    assert "selected_activities = eligible[:MAX_TILES]" in TNOW
    assert "empty_slots" in TNOW
    assert "capacity=%s" in TNOW
    assert "TNOW_GRID_SELECTED" in TNOW
    assert "MAX_TILES = 25" in TNOW


def test_spotify_pausado_tem_timestamp_para_recentes():
    assert 'mapped["player_timestamp_ms"] = timestamp_ms' in SPOTIFY
    assert 'mapped["played_at"] = datetime.fromtimestamp(' in SPOTIFY


def test_card_tem_status_visual_colorido_top_right_e_idade():
    assert "status: str = \"live\"" in CARD
    assert "age_minutes: int | None = None" in CARD
    assert "status-dot" in CARD
    for klass in (
        "status-live",
        "status-recent-15",
        "status-recent-30",
        "status-recent-45",
        "status-recent-120",
    ):
        assert klass in TEMPLATE
    assert "age-pill" in TEMPLATE
    assert "right: 10px" in TEMPLATE
    assert "#3FE0A6" in TEMPLATE
    assert "#FFD84A" in TEMPLATE
    assert "#FF9F1C" in TEMPLATE
    assert "#FF4D67" in TEMPLATE
    assert "#9AA0A6" in TEMPLATE


def test_card_saida_entre_quadrada_e_vertical_9_16():
    assert "MAX_CARD_ASPECT_HEIGHT_OVER_WIDTH = 16 / 9" in CARD
    assert "def _normalize_card_image" in CARD
    assert "if target_height < target_width:" in CARD
    assert "target_height = target_width" in CARD
    assert "min_width_for_vertical_limit = int(math.ceil" in CARD
    assert "max_allowed_height = int(math.floor" in CARD


def test_live_observado_continua_no_cache_e_degrada_por_tempo():
    assert "TNOW_LIVE_OBSERVED_TTL_SECONDS = 90" in CACHE
    assert "live_expires_at = observed_at + timedelta(seconds=TNOW_RECENT_120_SECONDS)" in CACHE
    assert 'status="live"' in CACHE
    assert "event_at = played_at or observed_at" in CACHE
