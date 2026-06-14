from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
BROADCAST = (ROOT / "app/bot/music_broadcast.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")


def _engine():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    return sqlalchemy.create_engine("sqlite+pysqlite:///:memory:", future=True)


def test_track_identity_accepts_tr4_lastfm_spotify_keys() -> None:
    from app.bot.music_broadcast_core import track_identity

    info = track_identity({
        "artist": "Björk",
        "track_name": "Jóga",
        "track_id": "lfm:abc",
        "album_image_url": "https://img.example/cover.jpg",
        "spotify_url": "https://open.spotify.com/track/123",
    })
    assert info["artist"] == "Björk"
    assert info["track_name"] == "Jóga"
    assert info["cover"] == "https://img.example/cover.jpg"
    assert info["url"] == "https://open.spotify.com/track/123"


def test_due_schedule_does_not_catch_up_old_slots() -> None:
    from app.bot.music_broadcast_core import create_music_broadcast_schedule, due_music_broadcast_schedules

    engine = _engine()
    create_music_broadcast_schedule(
        chat_id=-1001,
        title="Grupo",
        times="00:01,12:00",
        times_per_day=2,
        created_by=42,
        preview_confirmed=True,
        db_engine=engine,
    )
    assert due_music_broadcast_schedules(now=datetime(2026, 6, 10, 12, 0), db_engine=engine)
    assert due_music_broadcast_schedules(now=datetime(2026, 6, 10, 12, 1), db_engine=engine) == []


def test_schedule_defaults_to_unconfirmed_preview() -> None:
    from app.bot.music_broadcast_core import create_music_broadcast_schedule, due_music_broadcast_schedules

    engine = _engine()
    create_music_broadcast_schedule(chat_id=-1001, title="Grupo", times="12:00", created_by=42, db_engine=engine)
    assert due_music_broadcast_schedules(now=datetime(2026, 6, 10, 12, 0), db_engine=engine) == []


def test_manual_and_governante_broadcast_are_lastfm_current_only() -> None:
    assert "get_current_lastfm_track" in BROADCAST
    assert "manual não usa última música nem fallback Spotify" in BROADCAST
    assert "Nada está tocando agora no Last.fm." in BROADCAST
    manual_section = BROADCAST.split('@router.message(Command("tbrd", "broadcast"))', 1)[1]
    governante_section = BROADCAST.split("async def execute_governante_current_music_broadcast", 1)[1]
    assert "get_current_or_last_played(user_id)" not in manual_section
    assert "get_current_or_last_played(int(actor_user_id))" not in governante_section


def test_schedule_preview_endpoint_and_ui_confirmation_exist() -> None:
    assert '@router.post("/api/musica/broadcast/agendamentos/prever")' in ROUTER
    assert "preview_confirmed_required" in ROUTER
    assert "Confirme a prévia inicial" in ROUTER
    assert "/equalizador/api/musica/broadcast/agendamentos/prever" in ROUTER
    assert "clique novamente para confirmar" in ROUTER


def test_scheduler_records_no_music_failures() -> None:
    assert "_record_music_broadcast_failure" in BROADCAST
    assert '"sem música disponível"' in BROADCAST
    assert "record_music_broadcast_run" in BROADCAST


def test_daily_limit_summary_dm_scheduler_registered() -> None:
    assert "send_daily_limit_summary_to_owners" in MAIN
    assert "await send_daily_limit_summary_to_owners(bot)" in MAIN
