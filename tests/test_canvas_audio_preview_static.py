from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_processed_canvas_cache_tem_tabela_propria_e_migracao():
    model = read("app/models/canvas_processed_file.py")
    db = read("app/db/database.py")
    service = read("app/services/canvas_processed_cache.py")
    assert '__tablename__ = "canvas_processed_files"' in model
    for field in ("cache_key", "spotify_track_id", "canvas_fingerprint", "duration_ms", "process_kind", "process_version", "file_id"):
        assert field in model
    assert "CREATE TABLE IF NOT EXISTS canvas_processed_files" in db
    assert "from app.models.canvas_processed_file import CanvasProcessedFile" in db
    assert "class CanvasProcessedCacheService" in service
    assert "def put(" in service and "return True" in service


def test_spotify_preserva_preview_url_duration_e_market_no_lookup():
    spotify = read("app/services/spotify.py")
    assert '"preview_url": item.get("preview_url")' in spotify
    assert '"duration_ms": item.get("duration_ms")' in spotify
    assert 'async def get_track_by_id(self, track_id: str, market: str | None = "BR")' in spotify
    assert 'params = {"market": market} if market else None' in spotify
    assert 'params=params' in spotify


def test_canvas_audio_helper_e_atomico_e_limpa_temporarios():
    audio = read("app/services/canvas_audio.py")
    assert 'PROCESS_KIND = "canvas_preview_audio"' in audio
    assert "CANVAS_AUDIO_PREVIEW_ENABLED" in audio
    assert "get_canvas_bytes_cached" in audio
    assert "get_canvas_with_preview_asset" in audio
    assert 'spotify_service.get_track_by_id(canvas_track_id, market="BR")' in audio
    assert "_ffprobe_duration_seconds" in audio
    assert "_mux_canvas_with_preview" in audio
    assert '"-c:v"' in audio and '"copy"' in audio
    assert '"-c:a"' in audio and '"aac"' in audio
    assert "_DURATION_TOLERANCE_SECONDS" in audio
    assert "AUDIO_ARCHIVE_FAILED" in audio
    assert "AUDIO_CACHE_STORE_FAILED" in audio
    assert "os.remove(path)" in audio
    assert "return None" in audio


def test_tcanvas_tenta_audio_antes_do_canvas_bruto_e_mantem_fallback():
    delivery = read("app/bot/canvas_delivery.py")
    assert "get_canvas_with_preview_asset" in delivery
    assert "canvas_processed_cache_service" in delivery
    assert "Camada opcional: Canvas com preview oficial" in delivery
    assert "await _send_by_file_id(audio_asset.file_id, audio_cache_key=audio_asset.cache_key)" in delivery
    assert "# CACHE HIT (fast path, sem lock): reenvia por file_id." in delivery
    assert "return await _fallback()" in delivery


def test_tstory_usa_asset_com_audio_e_compose_preserva_audio_opcional():
    tstory = read("app/bot/tstory.py")
    video = read("app/services/tstory_video.py")
    assert "get_canvas_with_preview_asset" in tstory
    assert "TSTORY_AUDIO" in tstory
    assert "if audio_asset and audio_asset.bytes_data" in tstory
    assert "get_canvas_bytes_cached" in tstory
    assert '"-an"' not in video
    assert '"-map", "0:a?"' in video
    assert '"-shortest"' in video
    assert "[vout]" in video
