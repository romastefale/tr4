from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

import pytest


def test_phase32_router_exposes_maestro_config_endpoint_and_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    assert '@router.get("/api/configuracao")' in router
    assert 'Configuração do Maestro' in router
    assert 'config_raw' in router
    assert 'GROUP_ALIASES' in router
    assert 'palcos_ocultos' in router


def test_phase32_config_module_generates_raw_editor_without_secret_leak(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("GROUP_ALIASES", '{"radio":-1003818494866}')
    monkeypatch.setenv("TR4_EQUALIZADOR_ENABLED", "true")
    monkeypatch.setenv("TR4_EQUALIZADOR_APP_NAME", "equalizador")
    monkeypatch.setenv("TR4_EQUALIZADOR_MAESTRO_IDS", "8505890439")
    monkeypatch.setenv("TR4_EQUALIZADOR_OPERADOR_IDS", "8505890439,1759115970")
    monkeypatch.setenv("TR4_EQUALIZADOR_PALCO_IDS", "-1003818494866")
    monkeypatch.setenv("TR4_EQUALIZADOR_CANAIS", "8505890439:*:*")

    pytest.importorskip("sqlalchemy")
    import app.config.settings as settings

    reload(settings)
    from app.equalizador import configuracao

    raw = configuracao.raw_editor_equalizador_block()
    assert 'GROUP_ALIASES="{\\"radio\\":-1003818494866}"' in raw
    assert 'TR4_EQUALIZADOR_PALCO_IDS="-1003818494866"' in raw
    assert 'TR4_EQUALIZADOR_CANAIS="8505890439:*:*"' in raw
    assert "123:ABC" not in raw


def test_phase32_marks_unconfigured_palcos_as_hidden(tmp_path, monkeypatch) -> None:
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine, text

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("GROUP_ALIASES", '{"radio":-1003818494866}')
    monkeypatch.setenv("TR4_EQUALIZADOR_MAESTRO_IDS", "8505890439")
    monkeypatch.setenv("TR4_EQUALIZADOR_OPERADOR_IDS", "8505890439")
    monkeypatch.setenv("TR4_EQUALIZADOR_PALCO_IDS", "-1003818494866")
    monkeypatch.setenv("TR4_EQUALIZADOR_CANAIS", "8505890439:*:*")

    import app.config.settings as settings

    reload(settings)
    from app.equalizador.configuracao import configuracao_maestro_publica
    from app.equalizador.identity import make_ui_ref
    from app.equalizador.palcos import ensure_equalizador_tables

    db = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    ensure_equalizador_tables(db)
    with db.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_palcos (telegram_chat_id, titulo, ui_label, ui_ref, habilitado, updated_at)
                VALUES (:chat_id, :titulo, :ui_label, :ui_ref, 1, :updated_at)
                """
            ),
            {
                "chat_id": -1002556760909,
                "titulo": "geeks antigo",
                "ui_label": "geeks antigo",
                "ui_ref": make_ui_ref("grp", -1002556760909, settings.equalizador_alias_secret()),
                "updated_at": "2026-06-04T00:00:00+00:00",
            },
        )
    payload = configuracao_maestro_publica(alias_secret=settings.equalizador_alias_secret(), db_engine=db)
    assert [row["titulo"] for row in payload["palcos_ativos"]] == ["radio"]
    assert payload["palcos_ocultos"]
    assert payload["palcos_ocultos"][0]["estado"] == "oculto por configuração"
    serialized = repr(payload)
    assert "-1002556760909" not in serialized
