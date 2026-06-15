from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANVAS_ASSET = (ROOT / "app" / "services" / "canvas_asset.py").read_text(encoding="utf-8")
TSTORY = (ROOT / "app" / "bot" / "tstory.py").read_text(encoding="utf-8")
CANVAS_DELIVERY = (ROOT / "app" / "bot" / "canvas_delivery.py").read_text(encoding="utf-8")


def test_tstory_usa_canvas_asset_compartilhado():
    assert "from app.services.canvas_asset import get_canvas_bytes_cached" in TSTORY
    assert "spotify_canvas_service" not in TSTORY
    assert "spotify_service" not in TSTORY
    assert "get_canvas_bytes_cached(" in TSTORY
    assert "compose_story_video(canvas_bytes, overlay_png)" in TSTORY


def test_canvas_asset_reaproveita_file_id_do_cache():
    assert "canvas_cache_service.get_file_id" in CANVAS_ASSET
    assert "await bot.get_file(file_id)" in CANVAS_ASSET
    assert "await bot.download_file(file_path)" in CANVAS_ASSET
    assert "canvas_cache_service.forget" in CANVAS_ASSET
    assert "canvas_cache_service.lock" in CANVAS_ASSET


def test_canvas_asset_tem_cache_local_e_limites_de_segurança():
    assert "DATA_DIR" in CANVAS_ASSET
    assert "canvas_bytes" in CANVAS_ASSET
    assert "CANVAS_DOWNLOAD_MAX_BYTES" in CANVAS_ASSET
    assert "_CANVAS_MIN_BYTES" in CANVAS_ASSET
    assert "hashlib.sha256" in CANVAS_ASSET
    assert "tmp.replace(path)" in CANVAS_ASSET


def test_canvas_asset_sobe_no_canal_e_grava_db_quando_precisa():
    assert "CANVAS_CACHE_CHANNEL_ID" in CANVAS_ASSET
    assert "await bot.send_video(" in CANVAS_ASSET
    assert "BufferedInputFile(data" in CANVAS_ASSET
    assert "canvas_cache_service.put" in CANVAS_ASSET
    assert "_extract_file_ids" in CANVAS_ASSET


def test_tcanvas_continua_usando_entrega_por_file_id():
    assert "CACHE HIT" in CANVAS_DELIVERY
    assert "await _send_by_file_id(cached)" in CANVAS_DELIVERY
    assert "canvas_cache_service.put" in CANVAS_DELIVERY
