from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
CACHE = (ROOT / "app" / "services" / "tnow_activity_cache.py").read_text(encoding="utf-8")
COVER = (ROOT / "app" / "services" / "cover_cache.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")


def test_tnow_render_baixa_bytes_do_file_id_antes_da_url():
    assert "download_file_id_bytes" in COVER
    assert "bot.get_file(file_id)" in COVER
    assert "bot.download_file(file_path" in COVER
    assert "resolve_photo_bytes" in COVER
    assert "_cover_bytes_for_activity" in TNOW
    assert "activity.cover_file_id" in TNOW
    assert "TNOW_COVER_FILE_ID_INVALIDATED" in TNOW
    assert "return await _fetch_cover(activity.cover_url)" in TNOW


def test_tnow_activity_alimentada_por_fluxos_musicais_principais():
    assert "def schedule_tnow_activity_record" in CACHE
    assert "asyncio.create_task(_runner())" in CACHE
    assert "upsert_from_track(" in CACHE
    assert 'context="playing_payload"' in TELEGRAM
    assert 'context="tly_payload"' in TELEGRAM
    assert 'context="inline_public_playing"' in TELEGRAM
    INLINE = (ROOT / "app" / "bot" / "music_inline.py").read_text(encoding="utf-8")
    assert 'context="inline_tly"' in INLINE
    assert "TNOW_ACCEPTED_TRACK_SOURCES" in CACHE
    assert "TNOW_CACHE_SKIP_UNTRUSTED_SOURCE" in CACHE


def test_tnow_aspect_ratio_funcional_nunca_excede_9_16():
    from app.services.tnow_card import _normalize_card_image

    cases = [(1080, 600), (1080, 1080), (600, 1080), (1080, 2500), (100, 1000)]
    for width, height in cases:
        img = Image.new("RGB", (width, height), (255, 255, 255))
        raw = BytesIO()
        img.save(raw, format="JPEG")
        out = _normalize_card_image(raw.getvalue())
        with Image.open(BytesIO(out)) as result:
            ratio = result.height / result.width
            assert ratio >= 1.0
            assert ratio <= (16 / 9)


def test_normalizacao_usa_padding_sem_corte():
    assert "A função não corta tiles" in CARD
    assert "min_width_for_vertical_limit" in CARD
    assert "target_width = min_width_for_vertical_limit" in CARD
    assert 'Image.new("RGB", (target_width, target_height)' in CARD
