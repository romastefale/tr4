from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")


def _engine():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    return sqlalchemy.create_engine("sqlite+pysqlite:///:memory:", future=True)


def test_music_broadcast_blocks_can_be_listed_and_removed() -> None:
    from app.bot.music_broadcast_core import (  # noqa: PLC0415
        add_music_broadcast_block,
        is_music_broadcast_blocked,
        list_music_broadcast_blocks,
        remove_music_broadcast_block,
    )
    engine = _engine()
    add_music_broadcast_block(block_type="artist", value="Arctic Monkeys", created_by=1, db_engine=engine)
    blocks = list_music_broadcast_blocks(db_engine=engine)
    assert len(blocks) == 1
    assert blocks[0]["block_type"] == "artist"
    assert is_music_broadcast_blocked({"artist": "Arctic Monkeys", "track_name": "505"}, db_engine=engine)[0] is True
    assert remove_music_broadcast_block(block_id=blocks[0]["id"], db_engine=engine) is True
    assert list_music_broadcast_blocks(db_engine=engine) == []


def test_music_broadcast_schedule_due_mark_and_pause() -> None:
    from app.bot.music_broadcast_core import (  # noqa: PLC0415
        create_music_broadcast_schedule,
        due_music_broadcast_schedules,
        list_music_broadcast_schedules,
        mark_music_broadcast_schedule_run,
        set_music_broadcast_schedule_paused,
    )
    engine = _engine()
    schedule = create_music_broadcast_schedule(
        chat_id=-1001,
        title="Grupo",
        times="12:00,23:59",
        times_per_day=1,
        created_by=42,
        preview_confirmed=True,
        db_engine=engine,
    )
    due = due_music_broadcast_schedules(now=datetime(2026, 6, 10, 12, 0), db_engine=engine)
    assert [item["schedule_ref"] for item in due] == [schedule["schedule_ref"]]
    mark_music_broadcast_schedule_run(schedule_ref=schedule["schedule_ref"], due_slot=due[0]["due_slot"], sent=True, db_engine=engine)
    assert due_music_broadcast_schedules(now=datetime(2026, 6, 10, 12, 1), db_engine=engine) == []
    assert set_music_broadcast_schedule_paused(schedule_ref=schedule["schedule_ref"], paused=True, db_engine=engine) is True
    assert list_music_broadcast_schedules(db_engine=engine)[0]["paused"] is True


def test_owner_endpoints_and_ui_for_music_broadcast_exist() -> None:
    assert '@router.get("/api/musica/broadcast/config")' in ROUTER
    assert '@router.post("/api/musica/broadcast/bloqueios")' in ROUTER
    assert '@router.delete("/api/musica/broadcast/bloqueios/{block_id}")' in ROUTER
    assert '@router.post("/api/musica/broadcast/agendamentos")' in ROUTER
    assert '@router.post("/api/musica/broadcast/agendamentos/processar")' in ROUTER
    assert 'music_broadcast_owner_editor' in ROUTER
    assert 'music_broadcast_block_add' in ROUTER
    assert 'music_broadcast_schedule_create' in ROUTER
    assert 'daily_limit_summary' in ROUTER


def test_music_broadcast_scheduler_registered_and_show_surface_mentions_music() -> None:
    assert 'run_due_music_broadcast_schedules' in MAIN
    assert '_music_broadcast_scheduler_loop' in MAIN
    assert 'MUSIC_BROADCAST_SCHEDULER_SCHEDULED' in MAIN
    assert 'callback_data="show:music"' in SHOW
    assert 'music_broadcast_config_public' in SHOW


def test_daily_limit_summary_endpoint_exists() -> None:
    assert '@router.get("/api/governantes/limites/resumo-diario")' in ROUTER
    assert 'daily_limit_summary_public' in ROUTER
