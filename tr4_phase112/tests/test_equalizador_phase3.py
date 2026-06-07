from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text

from app.equalizador.afinacao import (
    canais_from_bot_rights,
    public_rights_from_member,
    sincronizar_afinacao_palco,
)
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables


def test_phase3_maps_bot_rights_to_public_channels() -> None:
    member = {
        "status": "administrator",
        "can_manage_chat": True,
        "can_delete_messages": True,
        "can_restrict_members": False,
        "can_invite_users": True,
        "can_pin_messages": False,
    }

    canais = {item["codigo"]: item for item in canais_from_bot_rights(member)}

    assert canais["mensagens.apagar"]["disponivel"] is True
    assert canais["reacoes.limpar"]["disponivel"] is True
    assert canais["convites.criar"]["disponivel"] is True
    assert canais["membros.silenciar"]["disponivel"] is False
    assert canais["fixados.criar"]["disponivel"] is False
    assert "can_restrict_members" in canais["membros.silenciar"]["faltando"]


def test_phase3_public_rights_do_not_include_ids_or_username() -> None:
    member = {
        "status": "administrator",
        "user": {"id": 123, "username": "botname"},
        "can_delete_messages": True,
        "can_restrict_members": True,
    }

    payload = public_rights_from_member(member)
    rendered = str(payload)

    assert payload["status"] == "administrator"
    assert payload["direitos"]["can_delete_messages"] is True
    assert "123" not in rendered
    assert "botname" not in rendered
    assert "username" not in rendered


@pytest.mark.asyncio
async def test_phase3_syncs_afinacao_snapshot_without_public_chat_id() -> None:
    db_engine = create_engine("sqlite:///:memory:", future=True)
    secret = "secret"
    chat_id = -100111222333
    grp_ref = make_ui_ref("grp", chat_id, secret)
    ensure_equalizador_tables(db_engine)
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

    async def fake_telegram_api_call(token: str, method: str, payload: dict | None) -> dict:
        assert token == "bot-token"
        if method == "getMe":
            return {"id": 555, "is_bot": True, "first_name": "Bot"}
        if method == "getChatMember":
            assert payload == {"chat_id": chat_id, "user_id": 555}
            return {
                "status": "administrator",
                "can_manage_chat": True,
                "can_delete_messages": True,
                "can_restrict_members": True,
                "can_invite_users": True,
                "can_pin_messages": True,
            }
        raise AssertionError(method)

    snapshot = await sincronizar_afinacao_palco(
        grp_ref=grp_ref,
        bot_token="bot-token",
        db_engine=db_engine,
        telegram_api_call=fake_telegram_api_call,
    )

    rendered = str(snapshot)
    assert snapshot["grp_ref"] == grp_ref
    assert snapshot["estado"] == "afinado"
    assert any(item["codigo"] == "mensagens.apagar" and item["disponivel"] for item in snapshot["canais"])
    assert str(chat_id) not in rendered
    assert "telegram_chat_id" not in rendered

    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT bot_rights_json, last_synced_at FROM eq_palcos WHERE ui_ref=:ui_ref"), {"ui_ref": grp_ref}).first()
    assert row is not None
    assert row[0]
    assert row[1]
