import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
create_engine = sqlalchemy.create_engine

from app.equalizador.ddx import list_ddx_publico, salvar_ddx_config, cancelar_ddx_agendado, ensure_ddx_tables
from app.equalizador.identity import make_ui_ref


def _engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'ddx.sqlite3'}")


def test_phase55_6_ddx_config_is_sanitized_and_persistent(tmp_path):
    engine = _engine(tmp_path)
    alias_secret = "secret"
    palco = {"telegram_chat_id": -1001234567890, "ui_ref": make_ui_ref("grp", -1001234567890, alias_secret)}
    filtro = salvar_ddx_config(
        palco=palco,
        ator_ref="usr_TESTE1",
        mode="hard",
        words="Banana, banana; Maçã verde\n  ",
        enabled=True,
        alias_secret=alias_secret,
        db_engine=engine,
    )
    assert filtro["enabled"] is True
    assert filtro["total_palavras"] == 2
    payload = list_ddx_publico(palco=palco, alias_secret=alias_secret, db_engine=engine)
    hard = [row for row in payload["filtros"] if row["modo"] == "hard"][0]
    assert hard["palavras"] == ["banana", "maçã verde"]
    assert payload["resumo"]["imediato_ativo"] is True


def test_phase55_6_ddx_cancel_rejects_unknown_ref(tmp_path):
    engine = _engine(tmp_path)
    alias_secret = "secret"
    palco = {"telegram_chat_id": -1001234567890, "ui_ref": make_ui_ref("grp", -1001234567890, alias_secret)}
    ensure_ddx_tables(engine)
    try:
        cancelar_ddx_agendado(palco=palco, scheduled_ref="ddx10_DESCONHECIDO", ator_ref="usr_TESTE1", db_engine=engine)
    except Exception as exc:
        assert exc.__class__.__name__ == "DDXNotFoundError"
    else:
        raise AssertionError("DDXNotFoundError esperado")
