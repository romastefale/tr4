from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text

from app.equalizador.maestro import (
    MAESTRO_CONFIRMATION_PHRASE,
    MaestroConfirmationError,
    build_silencio_payload,
    build_transmissao_payload,
    distribuicao_canais_publica,
)
from app.equalizador.permissions import canal_is_allowed

from app.equalizador.identity import make_ui_ref
from app.equalizador.maestro import executar_modo_silencio, executar_transmissao, exportar_historico_publico
from app.equalizador.mesa import ensure_phase5_tables, list_historico_publico, record_historico


def _db_engine():
    return create_engine("sqlite:///:memory:", future=True)


def _seed_palco(db_engine, *, chat_id: int, secret: str) -> str:
    ensure_phase5_tables(db_engine)
    grp_ref = make_ui_ref("grp", chat_id, secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_palcos (telegram_chat_id, titulo, ui_label, ui_ref, habilitado, updated_at)
                VALUES (:telegram_chat_id, :titulo, :ui_label, :ui_ref, 1, :updated_at)
                """
            ),
            {
                "telegram_chat_id": chat_id,
                "titulo": "Rádio Principal",
                "ui_label": "Rádio Principal",
                "ui_ref": grp_ref,
                "updated_at": "2026-06-04T00:00:00+00:00",
            },
        )
    return grp_ref


def test_phase6_critical_channels_remain_maestro_only() -> None:
    raw = "123:*:*;8505890439:*:*"

    assert canal_is_allowed(
        raw_canais=raw,
        user_id=123,
        chat_id=-100111,
        canal_codigo="silencio.ativar",
        is_maestro=False,
    ) is False
    assert canal_is_allowed(
        raw_canais=raw,
        user_id=8505890439,
        chat_id=-100111,
        canal_codigo="transmissao.enviar",
        is_maestro=True,
    ) is True


def test_phase6_requires_explicit_confirmation_for_critical_payloads() -> None:
    with pytest.raises(MaestroConfirmationError):
        build_silencio_payload(palco_id=-100111, payload={})

    payload = build_silencio_payload(
        palco_id=-100111,
        payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE},
    )

    assert payload["chat_id"] == -100111
    assert payload["permissions"]["can_send_messages"] is False


def test_phase6_transmission_payload_is_bounded_and_explicit() -> None:
    payload = build_transmissao_payload(
        palco_id=-100111,
        payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE, "texto": "Teste de mesa"},
    )

    assert payload["chat_id"] == -100111
    assert payload["text"] == "Teste de mesa"
    assert payload["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_phase6_executes_silent_mode_and_records_sanitized_history() -> None:
    db_engine = _db_engine()
    secret = "secret"
    chat_id = -100111222333
    grp_ref = _seed_palco(db_engine, chat_id=chat_id, secret=secret)
    calls: list[tuple[str, dict | None]] = []

    async def fake_telegram_api_call(token: str, method: str, payload: dict | None):
        calls.append((method, payload))
        if method == "getMe":
            return {"id": 555, "is_bot": True}
        if method == "getChatMember":
            return {"status": "administrator", "can_restrict_members": True}
        if method == "setChatPermissions":
            assert payload is not None
            assert payload["chat_id"] == chat_id
            return True
        raise AssertionError(method)

    result = await executar_modo_silencio(
        palco={"telegram_chat_id": chat_id, "ui_ref": grp_ref, "titulo": "Rádio Principal"},
        ator_ref="usr_MAESTRO",
        payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE},
        bot_token="bot-token",
        alias_secret=secret,
        db_engine=db_engine,
        telegram_api_call=fake_telegram_api_call,
    )

    assert result["ok"] is True
    assert result["ajuste"] == "silencio.ativar"
    assert str(chat_id) not in repr(result)
    history = list_historico_publico(palco_refs={grp_ref}, db_engine=db_engine)
    assert history[0]["ajuste"] == "silencio.ativar"
    assert str(chat_id) not in repr(history)
    assert [call[0] for call in calls] == ["getMe", "getChatMember", "setChatPermissions"]


@pytest.mark.asyncio
async def test_phase6_transmission_registers_message_ref_without_exposing_message_id() -> None:
    db_engine = _db_engine()
    secret = "secret"
    chat_id = -100111222333
    grp_ref = _seed_palco(db_engine, chat_id=chat_id, secret=secret)

    async def fake_telegram_api_call(token: str, method: str, payload: dict | None):
        if method == "getMe":
            return {"id": 555, "is_bot": True}
        if method == "getChatMember":
            return {"status": "administrator", "can_manage_chat": True}
        if method == "sendMessage":
            assert payload == {"chat_id": chat_id, "text": "Aviso", "disable_web_page_preview": True, "disable_notification": False}
            return {"message_id": 888, "chat": {"id": chat_id}}
        raise AssertionError(method)

    result = await executar_transmissao(
        palco={"telegram_chat_id": chat_id, "ui_ref": grp_ref, "titulo": "Rádio Principal"},
        ator_ref="usr_MAESTRO",
        payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE, "texto": "Aviso"},
        bot_token="bot-token",
        alias_secret=secret,
        db_engine=db_engine,
        telegram_api_call=fake_telegram_api_call,
    )

    assert result["ok"] is True
    assert result["msg_ref"].startswith("msg_")
    rendered = repr(result)
    assert str(chat_id) not in rendered
    assert "888" not in rendered


def test_phase6_export_and_distribution_are_sanitized() -> None:
    db_engine = _db_engine()
    secret = "secret"
    chat_id = -100111222333
    grp_ref = _seed_palco(db_engine, chat_id=chat_id, secret=secret)
    record_historico(
        ator_ref="usr_MAESTRO",
        palco_ref=grp_ref,
        alvo_ref=None,
        ajuste="silencio.ativar",
        status="concluido",
        resumo_publico="Modo silêncio ativado",
        payload_tecnico={"chat_id": chat_id},
        alias_secret=secret,
        db_engine=db_engine,
    )

    export = exportar_historico_publico(palco_refs={grp_ref}, alias_secret=secret, db_engine=db_engine)
    distribution = distribuicao_canais_publica(
        raw_canais=f"8505890439:{chat_id}:silencio.ativar,transmissao.enviar",
        allowed_palco_ids={chat_id},
        visible_palco_ids={chat_id},
        alias_secret=secret,
        db_engine=db_engine,
    )

    assert export["exportacao_ref"].startswith("exp_")
    assert export["registros"][0]["ajuste"] == "silencio.ativar"
    assert distribution[0]["operador"]["usr_ref"].startswith("usr_")
    assert distribution[0]["palco"]["grp_ref"] == grp_ref
    rendered = repr({"export": export, "distribution": distribution})
    assert str(chat_id) not in rendered
    assert "8505890439" not in rendered
    assert "payload_tecnico" not in rendered


def test_phase6_router_registers_maestro_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    maestro = (root / "app/equalizador/maestro.py").read_text()

    assert '@router.post("/api/palcos/{grp_ref}/silencio/ativar")' in router
    assert '@router.post("/api/palcos/{grp_ref}/transmissao/enviar")' in router
    assert '@router.get("/api/historico/exportar")' in router
    assert '@router.get("/api/canais/distribuicao")' in router
    assert "setChatPermissions" in maestro
    assert "sendMessage" in maestro
    assert "MAESTRO_CONFIRMATION_PHRASE" in maestro
