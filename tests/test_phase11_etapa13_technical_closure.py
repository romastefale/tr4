from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
BROADCAST = (ROOT / "app/bot/music_broadcast.py").read_text(encoding="utf-8")
CORE = (ROOT / "app/bot/music_broadcast_core.py").read_text(encoding="utf-8")
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")


def _engine():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    return sqlalchemy.create_engine("sqlite+pysqlite:///:memory:", future=True)


def test_manual_catalog_tables_and_selection_work() -> None:
    from app.bot.music_broadcast_core import (
        add_manual_music_catalog_item,
        choose_manual_catalog_track,
        list_manual_music_catalog,
        remove_manual_music_catalog_item,
    )

    engine = _engine()
    item = add_manual_music_catalog_item(
        artist="Björk",
        track_name="Jóga",
        cover_url="https://img.example/joga.jpg",
        spotify_url="https://open.spotify.com/track/123",
        created_by=42,
        db_engine=engine,
    )
    assert item["catalog_ref"].startswith("mbcat_")
    assert list_manual_music_catalog(db_engine=engine)[0]["artist"] == "Björk"
    track = choose_manual_catalog_track(db_engine=engine)
    assert track is not None
    assert track["source"] == "manual_catalog"
    assert track["track_name"] == "Jóga"
    assert remove_manual_music_catalog_item(catalog_ref=item["catalog_ref"], db_engine=engine)
    assert choose_manual_catalog_track(db_engine=engine) is None


def test_manual_catalog_respects_global_blocks() -> None:
    from app.bot.music_broadcast_core import add_manual_music_catalog_item, add_music_broadcast_block, choose_manual_catalog_track

    engine = _engine()
    add_manual_music_catalog_item(
        artist="Artist Blocked",
        track_name="Song",
        cover_url="https://img.example/song.jpg",
        created_by=42,
        db_engine=engine,
    )
    add_music_broadcast_block(block_type="artist", value="Artist Blocked", created_by=42, db_engine=engine)
    assert choose_manual_catalog_track(db_engine=engine) is None


def test_broadcast_commands_and_owner_catalog_endpoints_exist() -> None:
    assert "catalog add Artista - Música" in BROADCAST
    assert "add_manual_music_catalog_item" in BROADCAST
    assert "remove_manual_music_catalog_item" in BROADCAST
    assert '@router.post("/api/musica/broadcast/catalogo")' in ROUTER
    assert '@router.delete("/api/musica/broadcast/catalogo/{catalog_ref}")' in ROUTER
    assert "music_catalog_add" in ROUTER
    assert "music_broadcast_catalog" in ROUTER


def test_automatic_picker_uses_manual_catalog_before_known_profiles() -> None:
    assert "choose_manual_catalog_track" in BROADCAST
    section = BROADCAST.split("async def select_automatic_broadcast_track", 1)[1]
    assert section.index("choose_manual_catalog_track") < section.index("_registered_music_user_ids")
    assert "manual_catalog" in CORE
    assert "_recent_broadcast_keys" in CORE


def test_show_owner_ddx_buttons_and_message_flow_exist() -> None:
    assert "callback_data=\"show:ddx\"" in SHOW
    assert "show:ddx_enable" in SHOW
    assert "show:ddx_disable" in SHOW
    assert "show:ddx_add" in SHOW
    assert "awaiting\") == \"ddx_add_word\"" in SHOW
    assert "list_ddx_publico" in SHOW
    assert "salvar_ddx_config" in SHOW


def test_destructive_backend_confirmation_still_exists() -> None:
    assert "CONFIRMAR AJUSTE" in ROUTER
    assert "status_code=428" in ROUTER
    for action in ["mensagens.apagar", "membros.remover", "convites.revogar", "canais_remetentes.banir"]:
        assert action in ROUTER
