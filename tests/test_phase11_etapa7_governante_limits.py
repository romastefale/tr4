from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
SCOPE = (ROOT / "app/equalizador/governante_scope.py").read_text(encoding="utf-8")


def _imports():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from app.equalizador.governante_scope import (  # noqa: PLC0415
        GovernanteLimitError,
        check_governante_daily_limit,
        grant_governante_limit_exception,
        grant_governante_package,
        register_governante_usage,
        revoke_governante_limit_exception,
        set_governante_daily_limit,
    )
    from app.equalizador.identity import make_ui_ref  # noqa: PLC0415
    from app.equalizador.palcos import sync_allowed_palcos, upsert_operador  # noqa: PLC0415

    return {
        "create_engine": sqlalchemy.create_engine,
        "GovernanteLimitError": GovernanteLimitError,
        "check_governante_daily_limit": check_governante_daily_limit,
        "grant_governante_limit_exception": grant_governante_limit_exception,
        "grant_governante_package": grant_governante_package,
        "register_governante_usage": register_governante_usage,
        "revoke_governante_limit_exception": revoke_governante_limit_exception,
        "set_governante_daily_limit": set_governante_daily_limit,
        "make_ui_ref": make_ui_ref,
        "sync_allowed_palcos": sync_allowed_palcos,
        "upsert_operador": upsert_operador,
    }


def _engine():
    return _imports()["create_engine"]("sqlite+pysqlite:///:memory:", future=True)


def _seed_scope(engine):
    imp = _imports()
    secret = "phase11-etapa7"
    user_id = 7001
    chat_id = -1007001
    imp["upsert_operador"](
        user_id=user_id,
        user={"first_name": "Governante", "username": "gov"},
        perfil="Governante",
        alias_secret=secret,
        db_engine=engine,
    )
    imp["sync_allowed_palcos"](palco_ids={chat_id}, alias_secret=secret, db_engine=engine)
    usr_ref = imp["make_ui_ref"]("usr", user_id, secret)
    grp_ref = imp["make_ui_ref"]("grp", chat_id, secret)
    assignment = imp["grant_governante_package"](
        usr_ref=usr_ref,
        grp_ref=grp_ref,
        pacote="basico",
        granted_by_ref="usr_owner",
        alias_secret=secret,
        motivo="teste",
        db_engine=engine,
    )
    return secret, user_id, chat_id, assignment


def test_stage6_correction_uses_stable_assignment_ref_not_python_hash() -> None:
    assert "hashlib.sha256" in SCOPE
    assert "hash((seed, alias_secret))" not in SCOPE
    engine = _engine()
    imp = _imports()
    secret, user_id, chat_id, first = _seed_scope(engine)
    second = imp["grant_governante_package"](
        usr_ref=imp["make_ui_ref"]("usr", user_id, secret),
        grp_ref=imp["make_ui_ref"]("grp", chat_id, secret),
        pacote="basico",
        granted_by_ref="usr_owner",
        alias_secret=secret,
        motivo="teste 2",
        db_engine=engine,
    )
    assert first["assignment_ref"] == second["assignment_ref"]


def test_daily_limit_blocks_after_configured_amount_and_reports_payload() -> None:
    engine = _engine()
    imp = _imports()
    _secret, user_id, chat_id, assignment = _seed_scope(engine)
    imp["set_governante_daily_limit"](
        assignment_ref=str(assignment["assignment_ref"]),
        action="mensagens.enviar",
        daily_limit=1,
        updated_by_ref="usr_owner",
        db_engine=engine,
    )
    before = imp["check_governante_daily_limit"](
        user_id=user_id,
        chat_id=chat_id,
        action="mensagens.enviar",
        is_maestro=False,
        db_engine=engine,
    )
    assert before["remaining"] == 1
    imp["register_governante_usage"](user_id=user_id, chat_id=chat_id, action="mensagens.enviar", db_engine=engine)
    with pytest.raises(imp["GovernanteLimitError"]) as err:
        imp["check_governante_daily_limit"](
            user_id=user_id,
            chat_id=chat_id,
            action="mensagens.enviar",
            is_maestro=False,
            db_engine=engine,
        )
    assert err.value.payload()["code"] == "limite_diario_atingido"
    assert err.value.payload()["daily_limit"] == 1
    assert err.value.payload()["used_count"] == 1


def test_24h_exception_bypasses_limit_and_can_be_revoked() -> None:
    engine = _engine()
    imp = _imports()
    secret, user_id, chat_id, assignment = _seed_scope(engine)
    imp["set_governante_daily_limit"](
        assignment_ref=str(assignment["assignment_ref"]),
        action="mensagens.enviar",
        daily_limit=1,
        updated_by_ref="usr_owner",
        db_engine=engine,
    )
    imp["register_governante_usage"](user_id=user_id, chat_id=chat_id, action="mensagens.enviar", db_engine=engine)
    exception = imp["grant_governante_limit_exception"](
        assignment_ref=str(assignment["assignment_ref"]),
        action="mensagens.enviar",
        created_by_ref="usr_owner",
        alias_secret=secret,
        hours=24,
        db_engine=engine,
    )
    allowed = imp["check_governante_daily_limit"](
        user_id=user_id,
        chat_id=chat_id,
        action="mensagens.enviar",
        is_maestro=False,
        db_engine=engine,
    )
    assert allowed["exception_active"] is True
    assert imp["revoke_governante_limit_exception"](exception_ref=str(exception["exception_ref"]), revoked_by_ref="usr_owner", db_engine=engine)
    with pytest.raises(imp["GovernanteLimitError"]):
        imp["check_governante_daily_limit"](
            user_id=user_id,
            chat_id=chat_id,
            action="mensagens.enviar",
            is_maestro=False,
            db_engine=engine,
        )


def test_router_enforces_limits_notifies_owner_and_exposes_exception_endpoints() -> None:
    assert "check_governante_daily_limit(" in ROUTER
    assert "EQUALIZADOR_GOVERNANTE_LIMITE_ATINGIDO" in ROUTER
    assert "await _notify_maestros_governante_limit" in ROUTER
    assert '@router.post("/api/governantes/pacotes/{assignment_ref}/excecoes")' in ROUTER
    assert '@router.delete("/api/governantes/excecoes/{exception_ref}")' in ROUTER
