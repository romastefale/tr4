from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text

from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import (
    ACTION_SPECS,
    build_action_payload,
    ensure_bot_right,
    ensure_phase5_tables,
    executar_ajuste,
    list_historico_publico,
    register_alvo_ref,
    register_mensagem_ref,
)


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


def test_phase5_registers_message_and_target_refs_without_public_raw_ids() -> None:
    db_engine = create_engine("sqlite:///:memory:", future=True)
    secret = "secret"
    chat_id = -100111222333

    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=777,
        resumo_publico="Mensagem de teste",
        alias_secret=secret,
        db_engine=db_engine,
    )
    alvo_ref = register_alvo_ref(
        chat_id=chat_id,
        user_id=123456,
        nome_publico="Piero",
        alias_secret=secret,
        db_engine=db_engine,
    )

    assert msg_ref.startswith("msg_")
    assert alvo_ref.startswith("usr_")
    rendered = repr({"msg_ref": msg_ref, "alvo_ref": alvo_ref})
    assert str(chat_id) not in rendered
    assert "777" not in rendered
    assert "123456" not in rendered


def test_phase5_builds_bot_payload_only_after_resolving_public_message_ref() -> None:
    db_engine = create_engine("sqlite:///:memory:", future=True)
    secret = "secret"
    chat_id = -100111222333
    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=777,
        resumo_publico="Mensagem de teste",
        alias_secret=secret,
        db_engine=db_engine,
    )

    payload, alvo_ref, label = build_action_payload(
        ajuste="mensagens.apagar",
        palco_id=chat_id,
        payload={"msg_ref": msg_ref},
        db_engine=db_engine,
    )

    assert payload == {"chat_id": chat_id, "message_id": 777}
    assert alvo_ref == msg_ref
    assert label == "Mensagem de teste"


@pytest.mark.asyncio
async def test_phase5_checks_real_bot_right_before_action() -> None:
    calls: list[tuple[str, dict | None]] = []

    async def fake_telegram_api_call(token: str, method: str, payload: dict | None):
        calls.append((method, payload))
        if method == "getMe":
            return {"id": 555, "is_bot": True}
        if method == "getChatMember":
            return {"status": "administrator", "can_delete_messages": True}
        raise AssertionError(method)

    await ensure_bot_right(
        bot_token="bot-token",
        chat_id=-100111222333,
        required_right="can_delete_messages",
        telegram_api_call=fake_telegram_api_call,
    )

    assert calls == [
        ("getMe", None),
        ("getChatMember", {"chat_id": -100111222333, "user_id": 555}),
    ]


@pytest.mark.asyncio
async def test_phase5_executes_delete_message_and_records_sanitized_history() -> None:
    db_engine = create_engine("sqlite:///:memory:", future=True)
    secret = "secret"
    chat_id = -100111222333
    grp_ref = _seed_palco(db_engine, chat_id=chat_id, secret=secret)
    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=777,
        resumo_publico="Mensagem de teste",
        alias_secret=secret,
        db_engine=db_engine,
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_telegram_api_call(token: str, method: str, payload: dict | None):
        assert token == "bot-token"
        calls.append((method, payload))
        if method == "getMe":
            return {"id": 555, "is_bot": True}
        if method == "getChatMember":
            return {"status": "administrator", "can_delete_messages": True}
        if method == "deleteMessage":
            assert payload == {"chat_id": chat_id, "message_id": 777}
            return True
        raise AssertionError(method)

    result = await executar_ajuste(
        ajuste="mensagens.apagar",
        palco={"telegram_chat_id": chat_id, "ui_ref": grp_ref, "titulo": "Rádio Principal"},
        ator_ref="usr_OPERADOR",
        payload={"msg_ref": msg_ref},
        bot_token="bot-token",
        alias_secret=secret,
        db_engine=db_engine,
        telegram_api_call=fake_telegram_api_call,
    )

    assert result["ok"] is True
    assert result["status"] == "concluido"
    assert result["historico_ref"].startswith("his_")
    rendered = repr(result)
    assert str(chat_id) not in rendered
    assert "777" not in rendered

    history = list_historico_publico(palco_refs={grp_ref}, db_engine=db_engine)
    assert len(history) == 1
    assert history[0]["ajuste"] == "mensagens.apagar"
    assert history[0]["status"] == "concluido"
    assert str(chat_id) not in repr(history)
    assert "777" not in repr(history)

    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT payload_tecnico_json FROM eq_historico")).first()
    assert row is not None
    assert str(chat_id) in row[0]
    assert "777" in row[0]


def test_phase5_router_registers_light_action_routes_and_historico() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    mesa = (root / "app/equalizador/mesa.py").read_text()

    assert '@router.get("/api/historico")' in router
    assert '@router.post("/api/palcos/{grp_ref}/mensagens/apagar")' in router
    assert '@router.post("/api/palcos/{grp_ref}/membros/silenciar")' in router
    assert '@router.post("/api/palcos/{grp_ref}/convites/criar")' in router
    assert "deleteMessage" in mesa
    assert "restrictChatMember" in mesa
    assert "banChatMember" in mesa
    assert "unbanChatMember" in mesa
    assert "pinChatMessage" in mesa
    assert "createChatInviteLink" in mesa


def test_phase5_public_action_specs_match_granted_channels() -> None:
    assert ACTION_SPECS["mensagens.apagar"].canal_codigo == "mensagens.apagar"
    assert ACTION_SPECS["membros.silenciar"].canal_codigo == "membros.silenciar"
    assert ACTION_SPECS["fixados.criar"].canal_codigo == "fixados.criar"
