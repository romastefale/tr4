from __future__ import annotations

from app.db.database import engine
from app.security import private_panels as pp


def test_private_panel_upsert_roundtrip():
    pp.ensure_tables()
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("DELETE FROM private_panels"))
    pp.upsert_panel(actor_user_id=1, chat_id=10, message_id=20, panel_type="tigrao")
    row = pp.get_panel(1)
    assert row is not None
    assert row["chat_id"] == 10
    assert row["message_id"] == 20
    pp.upsert_panel(actor_user_id=1, chat_id=10, message_id=21, panel_type="tigrao")
    row = pp.get_panel(1)
    assert row is not None
    assert row["message_id"] == 21


def test_ephemeral_record_lifecycle():
    pp.ensure_tables()
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("DELETE FROM ephemeral_messages"))
    pp.remember_ephemeral(actor_user_id=1, chat_id=10, message_id=99, reason="x")
    rows = pp.list_ephemeral(1)
    assert len(rows) == 1
    pp.delete_ephemeral_record(rows[0]["id"])
    assert pp.list_ephemeral(1) == []
