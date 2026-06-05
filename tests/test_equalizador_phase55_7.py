import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
create_engine = sqlalchemy.create_engine

from app.config import settings
from app.equalizador.identity import make_ui_ref
from app.equalizador.reacoes import ensure_reacoes_tables, list_reacoes_publicas, record_reaction_update_payload


def _engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'reacoes.sqlite3'}")


def test_phase55_7_reaction_update_creates_public_audit_without_numeric_id(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    alias_secret = "secret"
    chat_id = -1001234567890
    monkeypatch.setattr(settings, "TR4_EQUALIZADOR_PALCO_IDS_SET", {chat_id})
    ensure_reacoes_tables(engine)
    payload = {
        "update_id": 10,
        "message_reaction": {
            "chat": {"id": chat_id, "type": "supergroup", "title": "Grupo Teste"},
            "message_id": 222,
            "date": 1710000000,
            "user": {"id": 7946870636, "first_name": "Operador", "username": "operador_teste"},
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": "🔥"}],
        },
    }
    assert record_reaction_update_payload(payload, alias_secret=alias_secret, db_engine=engine) is True
    palco = {"telegram_chat_id": chat_id, "ui_ref": make_ui_ref("grp", chat_id, alias_secret)}
    data = list_reacoes_publicas(palco=palco, db_engine=engine)
    assert data["eventos"]
    assert data["recentes"]
    public_text = str(data)
    assert "7946870636" not in public_text
    assert "-1001234567890" not in public_text
    assert "operador_teste" in public_text
    assert "🔥" in public_text


def test_phase55_7_ignores_reactions_outside_allowed_palcos(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    monkeypatch.setattr(settings, "TR4_EQUALIZADOR_PALCO_IDS_SET", {-1009999999999})
    payload = {
        "message_reaction": {
            "chat": {"id": -1001234567890, "type": "supergroup"},
            "message_id": 1,
            "date": 1710000000,
            "user": {"id": 123, "first_name": "A"},
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": "👍"}],
        }
    }
    assert record_reaction_update_payload(payload, alias_secret="secret", db_engine=engine) is False
