from __future__ import annotations

from pathlib import Path


def test_phase41_router_exposes_dynamic_panel() -> None:
    router = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert '@router.get("/api/palcos/{grp_ref}/painel")' in router
    assert "montar_painel_dinamico_palco" in router
    assert "Painel dinâmico" in router
    assert "Lista de administração" in router
    assert "Bots administradores" in router


def test_phase41_dynamic_actions_follow_real_rights() -> None:
    import pytest
    pytest.importorskip("sqlalchemy")
    from app.equalizador.painel import dynamic_action_rows

    rows = dynamic_action_rows(
        {
            "status": "administrator",
            "can_delete_messages": True,
            "can_pin_messages": False,
            "can_restrict_members": True,
            "can_invite_users": True,
            "can_change_info": False,
            "can_manage_topics": False,
            "can_promote_members": False,
        }
    )
    by_code = {str(row["codigo"]): row for row in rows}
    assert by_code["mensagens.apagar"]["disponivel"] is True
    assert by_code["membros.silenciar"]["disponivel"] is True
    assert by_code["convites.criar"]["disponivel"] is True
    assert by_code["fixados.criar"]["disponivel"] is False
    assert by_code["grupo.titulo"]["disponivel"] is False
    assert by_code["admins.promover"]["diagnostico"] is True


def test_phase41_admin_public_payload_is_sanitized() -> None:
    import pytest
    pytest.importorskip("sqlalchemy")
    from app.equalizador.painel import _admin_public

    payload = _admin_public(
        {
            "status": "administrator",
            "custom_title": "Dono técnico",
            "user": {"id": 1759115970, "first_name": "Operador", "username": "operador_publico", "is_bot": False},
            "can_delete_messages": True,
        },
        alias_secret="secret",
    )
    serialized = repr(payload)
    assert "1759115970" not in serialized
    assert "@" not in serialized
    assert payload["usr_ref"].startswith("usr_")
    assert payload["perfil_admin"] == "Administrador"
    assert any(row["codigo"] == "can_delete_messages" and row["concedido"] is True for row in payload["direitos"])
