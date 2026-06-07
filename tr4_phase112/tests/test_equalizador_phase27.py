from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_equalizador_phase27_afinacao_includes_maestro_operational_channels() -> None:
    source = read("app/equalizador/afinacao.py")
    assert '"codigo": "silencio.ativar"' in source
    assert '"direitos": ("can_restrict_members",)' in source
    assert '"codigo": "transmissao.enviar"' in source
    assert '"direitos": ("can_manage_chat",)' in source


def test_equalizador_phase27_ui_does_not_bypass_afinacao_for_maestro_actions() -> None:
    source = read("app/equalizador/router.py")
    script = source.split("<script", 1)[1]
    can_run_start = script.index("const canRun")
    can_run_body = script[can_run_start: script.index("function fillSelect", can_run_start)]
    assert 'direitosDisponiveis.has(codigo)' in can_run_body
    assert 'codigo === "transmissao.enviar"' not in can_run_body
    assert 'codigo === "silencio.ativar"' not in can_run_body
    assert 'codigo === "convites.criar"' not in can_run_body


def test_equalizador_phase27_maestro_errors_are_sanitized_and_specific() -> None:
    source = read("app/equalizador/maestro.py")
    router = read("app/equalizador/router.py")
    assert "def maestro_error_public_detail" in source
    assert '"transmissao_vazia": "Escreva o texto da transmissão."' in source
    assert '"transmissao_longa": "Transmissão acima do limite do Telegram."' in source
    assert "maestro_error_public_detail(exc)" in router
    assert 'detail="Ajuste não concluído."' not in router


def test_equalizador_phase27_export_reports_total_without_technical_payload() -> None:
    source = read("app/equalizador/maestro.py")
    router = read("app/equalizador/router.py")
    assert '"total_registros": len(rows)' in source
    assert "payload_tecnico" not in source.split("def exportar_historico_publico", 1)[1].split("def distribuicao_canais_publica", 1)[0]
    assert "total_registros" in router


sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text

from app.equalizador.afinacao import canais_from_bot_rights
from app.equalizador.identity import make_ui_ref
from app.equalizador.maestro import exportar_historico_publico, maestro_error_public_detail, MaestroError
from app.equalizador.mesa import ensure_phase5_tables, record_historico


def test_equalizador_phase27_afinacao_maps_real_rights_to_maestro_channels() -> None:
    member = {
        "status": "administrator",
        "can_restrict_members": True,
        "can_manage_chat": False,
    }
    rows = {row["codigo"]: row for row in canais_from_bot_rights(member)}
    assert rows["silencio.ativar"]["disponivel"] is True
    assert rows["transmissao.enviar"]["disponivel"] is False
    assert rows["transmissao.enviar"]["faltando"] == ["can_manage_chat"]


def test_equalizador_phase27_export_is_sanitized_with_count() -> None:
    db_engine = create_engine("sqlite:///:memory:", future=True)
    secret = "secret"
    chat_id = -1001234567890
    ensure_phase5_tables(db_engine)
    grp_ref = make_ui_ref("grp", chat_id, secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_palcos (telegram_chat_id, titulo, ui_label, ui_ref, habilitado, updated_at)
                VALUES (:chat_id, 'Palco', 'Palco', :grp_ref, 1, '2026-06-04T00:00:00+00:00')
                """
            ),
            {"chat_id": chat_id, "grp_ref": grp_ref},
        )
    record_historico(
        ator_ref="usr_MAESTRO",
        palco_ref=grp_ref,
        alvo_ref=None,
        ajuste="transmissao.enviar",
        status="concluido",
        resumo_publico="Transmissão enviada",
        payload_tecnico={"chat_id": chat_id, "message_id": 12345},
        alias_secret=secret,
        db_engine=db_engine,
    )
    export = exportar_historico_publico(palco_refs={grp_ref}, alias_secret=secret, db_engine=db_engine)
    assert export["total_registros"] == 1
    rendered = repr(export)
    assert str(chat_id) not in rendered
    assert "12345" not in rendered
    assert "payload_tecnico" not in rendered


def test_equalizador_phase27_maestro_error_public_detail_maps_known_errors() -> None:
    assert maestro_error_public_detail(MaestroError("transmissao_vazia")) == "Escreva o texto da transmissão."
    assert maestro_error_public_detail(MaestroError("transmissao_longa")) == "Transmissão acima do limite do Telegram."
