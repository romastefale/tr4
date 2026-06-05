from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from app.equalizador.admin import ADMIN_SPECS, build_admin_payload, require_extreme_confirmation, AdminConfirmationError
from app.equalizador.afinacao import canais_from_bot_rights
from app.equalizador.permissions import CANAL_BY_CODE, CRITICAL_CANAL_CODES
from app.equalizador.mesa import ensure_phase5_tables


def test_phase45_channels_registered_as_critical() -> None:
    for code in ["grupo.titulo", "grupo.descricao", "admins.promover", "admins.rebaixar", "admins.titulo"]:
        assert code in CANAL_BY_CODE
        assert code in CRITICAL_CANAL_CODES


def test_phase45_afinacao_maps_admin_rights() -> None:
    rows = canais_from_bot_rights({
        "status": "administrator",
        "can_change_info": True,
        "can_promote_members": True,
    })
    available = {row["codigo"] for row in rows if row["disponivel"]}
    assert "grupo.titulo" in available
    assert "grupo.descricao" in available
    assert "admins.promover" in available
    assert "admins.rebaixar" in available
    assert "admins.titulo" in available


def test_phase45_specs_use_real_telegram_methods() -> None:
    assert ADMIN_SPECS["grupo.titulo"].telegram_method == "setChatTitle"
    assert ADMIN_SPECS["grupo.descricao"].telegram_method == "setChatDescription"
    assert ADMIN_SPECS["admins.promover"].telegram_method == "promoteChatMember"
    assert ADMIN_SPECS["admins.rebaixar"].telegram_method == "promoteChatMember"
    assert ADMIN_SPECS["admins.titulo"].telegram_method == "setChatAdministratorCustomTitle"


def test_phase45_confirmation_is_required() -> None:
    with pytest.raises(AdminConfirmationError):
        require_extreme_confirmation({"confirmacao": "CONFIRMAR AJUSTE"})
    with pytest.raises(AdminConfirmationError):
        require_extreme_confirmation({"ciente": True})
    require_extreme_confirmation({"confirmacao": "CONFIRMAR AJUSTE", "ciente": True})


def test_phase45_group_payloads_do_not_need_raw_ids(tmp_path) -> None:
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path/'phase45.db'}")
    ensure_phase5_tables(engine)
    payload, alvo_ref, label = build_admin_payload(
        ajuste="grupo.titulo",
        palco_id=-1001,
        payload={"titulo": "Novo título", "confirmacao": "CONFIRMAR AJUSTE", "ciente": True},
        db_engine=engine,
    )
    assert payload == {"chat_id": -1001, "title": "Novo título"}
    assert alvo_ref is None
    assert label == "Novo título"


def test_phase45_router_has_admin_ui_and_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert "Administração crítica" in router
    assert 'data-action="grupo.titulo"' in router
    assert '@router.post("/api/palcos/{grp_ref}/grupo/titulo")' in router
    assert '@router.post("/api/palcos/{grp_ref}/admins/promover")' in router
