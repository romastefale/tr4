from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
create_engine = sqlalchemy.create_engine
text = sqlalchemy.text

from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import list_equalizador_palcos, upsert_operador


def _sqlite_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'equalizador_phase2.sqlite3'}", connect_args={"check_same_thread": False})


def test_equalizador_phase2_persists_operator_with_sanitized_alias(tmp_path):
    engine = _sqlite_engine(tmp_path)

    operador = upsert_operador(
        user_id=8505890439,
        user={"id": 8505890439, "first_name": "Piero", "username": "nao_expor"},
        perfil="Maestro",
        alias_secret="phase2-secret",
        db_engine=engine,
    )

    assert operador["ui_ref"].startswith("usr_")
    assert "8505890439" not in operador["ui_ref"]
    assert operador == {
        "ui_ref": make_ui_ref("usr", 8505890439, "phase2-secret"),
        "nome": "Piero",
        "perfil": "Maestro",
    }

    with engine.begin() as conn:
        row = conn.execute(text("SELECT telegram_user_id, username, ui_ref FROM eq_operadores")).mappings().one()
    assert row["telegram_user_id"] == 8505890439
    assert row["username"] == "nao_expor"
    assert row["ui_ref"] == operador["ui_ref"]


def test_equalizador_phase2_lists_only_aliases_and_titles_for_allowed_palcos(tmp_path):
    engine = _sqlite_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE music_groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO music_groups (chat_id, title, username, updated_at) VALUES (:chat_id, :title, :username, :updated_at)"),
            {
                "chat_id": -1003818494866,
                "title": "Rádio Principal",
                "username": "radio_principal",
                "updated_at": "2026-06-04T20:00:00+00:00",
            },
        )

    palcos = list_equalizador_palcos(
        palco_ids={-1003818494866},
        alias_secret="phase2-secret",
        db_engine=engine,
    )

    assert palcos == [
        {
            "grp_ref": make_ui_ref("grp", -1003818494866, "phase2-secret"),
            "titulo": "Rádio Principal",
            "estado": "habilitado",
            "afinacao": "pendente",
        }
    ]
    serialized = repr(palcos)
    assert "-1003818494866" not in serialized
    assert "radio_principal" not in serialized
    assert "@" not in serialized

    with engine.begin() as conn:
        row = conn.execute(text("SELECT telegram_chat_id, username, ui_ref, ui_label FROM eq_palcos")).mappings().one()
    assert row["telegram_chat_id"] == -1003818494866
    assert row["username"] == "radio_principal"
    assert row["ui_ref"] == palcos[0]["grp_ref"]
    assert row["ui_label"] == "Rádio Principal"


def test_equalizador_phase2_unknown_palco_uses_neutral_title_without_id(tmp_path):
    engine = _sqlite_engine(tmp_path)

    palcos = list_equalizador_palcos(
        palco_ids={-1009999999999},
        alias_secret="phase2-secret",
        db_engine=engine,
    )

    assert palcos[0]["titulo"] == "Palco sem título"
    assert palcos[0]["grp_ref"].startswith("grp_")
    assert "-1009999999999" not in repr(palcos)
