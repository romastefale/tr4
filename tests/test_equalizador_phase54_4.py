from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")


def test_phase54_4_router_has_people_windows() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="admins_humanos_lista"' in router
    assert 'id="bots_admins_lista"' in router
    assert 'id="admin_alvo_select"' in router
    assert "sem exibir ID real" in router
    assert "Administradores humanos" in router


def test_phase54_4_admin_public_registers_internal_target(tmp_path) -> None:
    from sqlalchemy import create_engine
    from app.equalizador.mesa import ensure_phase5_tables, resolve_alvo_ref
    from app.equalizador.painel import _admin_public

    engine = create_engine(f"sqlite:///{tmp_path/'phase54_4.db'}")
    ensure_phase5_tables(engine)
    payload = _admin_public(
        {
            "status": "administrator",
            "user": {"id": 1759115970, "first_name": "Operador", "username": "operador_publico", "is_bot": False},
            "can_promote_members": True,
        },
        alias_secret="secret",
        chat_id=-100123,
        db_engine=engine,
    )
    assert payload["alvo_ref"].startswith("usr_")
    assert "1759115970" not in repr(payload)
    resolved = resolve_alvo_ref(palco_id=-100123, alvo_ref=str(payload["alvo_ref"]), db_engine=engine)
    assert int(resolved["telegram_user_id"]) == 1759115970


def test_phase54_4_dynamic_panel_separates_humans_and_bots(monkeypatch, tmp_path) -> None:
    from sqlalchemy import create_engine
    from app.equalizador.painel import montar_painel_dinamico_palco
    from app.equalizador.identity import make_ui_ref
    from app.equalizador.palcos import sync_allowed_palcos

    engine = create_engine(f"sqlite:///{tmp_path/'phase54_4_panel.db'}")
    sync_allowed_palcos(palco_ids=[-100123], alias_secret="secret", db_engine=engine)

    async def fake_api(_token: str, method: str, payload):
        if method == "getMe":
            return {"id": 10, "first_name": "Bot"}
        if method == "getChat":
            return {"id": -100123, "title": "Grupo", "type": "supergroup"}
        if method == "getChatMemberCount":
            return 2
        if method == "getChatMember":
            return {"status": "administrator", "can_manage_chat": True, "can_promote_members": True}
        if method == "getChatAdministrators":
            return [
                {"status": "administrator", "user": {"id": 20, "first_name": "Humano", "username": "humano_ok", "is_bot": False}, "can_delete_messages": True},
                {"status": "administrator", "user": {"id": 30, "first_name": "Robo", "username": "robo_ok", "is_bot": True}, "can_delete_messages": True},
            ]
        raise AssertionError(method)

    import asyncio
    payload = asyncio.run(montar_painel_dinamico_palco(
        grp_ref=make_ui_ref("grp", -100123, "secret"),
        bot_token="token",
        alias_secret="secret",
        db_engine=engine,
        telegram_api_call=fake_api,
    ))
    assert payload["resumo"]["administradores_humanos"] == 1
    assert payload["resumo"]["bots_administradores"] == 1
    assert payload["administradores_humanos"][0]["alvo_ref"].startswith("usr_")
    assert payload["bots_administradores"][0]["bot"] is True
