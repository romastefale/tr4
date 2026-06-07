from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.equalizador.hardening import (
    EqualizadorMesaBusyError,
    EqualizadorRateLimitError,
    EqualizadorSessionError,
    check_equalizador_rate_limit,
    create_equalizador_session,
    equalizador_hardening_status,
    log_equalizador_event,
    mesa_operation_lock,
    reset_equalizador_locks,
    reset_equalizador_rate_limits,
    reset_equalizador_sessions,
    sanitize_ref,
    validate_equalizador_session,
)
from app.equalizador.security import TelegramWebAppIdentity


def test_phase7_rate_limit_is_per_operator_alias() -> None:
    reset_equalizador_rate_limits()
    check_equalizador_rate_limit(operator_ref="usr_AAAAAAAA", limit_per_minute=2, now=1000.0)
    check_equalizador_rate_limit(operator_ref="usr_AAAAAAAA", limit_per_minute=2, now=1001.0)

    with pytest.raises(EqualizadorRateLimitError):
        check_equalizador_rate_limit(operator_ref="usr_AAAAAAAA", limit_per_minute=2, now=1002.0)

    # Outro operador não herda a janela do primeiro.
    result = check_equalizador_rate_limit(operator_ref="usr_BBBBBBBB", limit_per_minute=2, now=1002.0)
    assert result["allowed"] is True


def test_phase7_short_session_is_opaque_and_expires() -> None:
    reset_equalizador_sessions()
    identity = TelegramWebAppIdentity(user_id=8505890439, user={"id": 8505890439, "first_name": "Piero"}, auth_date=1000)

    session = create_equalizador_session(identity=identity, ttl_seconds=60, now=1000)

    token = str(session["token"])
    assert token
    assert "8505890439" not in token
    assert validate_equalizador_session(token, now=1059).user_id == 8505890439
    with pytest.raises(EqualizadorSessionError):
        validate_equalizador_session(token, now=1061)


@pytest.mark.asyncio
async def test_phase7_mesa_lock_rejects_concurrent_action() -> None:
    reset_equalizador_locks()

    async with mesa_operation_lock("grp_AAAAAAAA:mensagens.apagar"):
        with pytest.raises(EqualizadorMesaBusyError):
            async with mesa_operation_lock("grp_AAAAAAAA:mensagens.apagar", timeout_seconds=0.001):
                pass

    # Depois de liberar, o mesmo lock pode ser usado de novo.
    async with mesa_operation_lock("grp_AAAAAAAA:mensagens.apagar"):
        await asyncio.sleep(0)


def test_phase7_sanitized_log_does_not_emit_raw_ids_or_username(caplog) -> None:
    caplog.set_level("INFO")

    assert sanitize_ref("8505890439") == "ref_oculta"
    log_equalizador_event(
        "EQUALIZADOR_AJUSTE_OK",
        ator_ref="8505890439",
        palco_ref="-100111222333",
        ajuste="mensagens.apagar",
    )

    rendered = caplog.text
    assert "8505890439" not in rendered
    assert "-100111222333" not in rendered
    assert "@" not in rendered
    assert "ref_oculta" in rendered
    assert "mensagens.apagar" in rendered


def test_phase7_readyz_status_has_hardening_metadata_without_ids() -> None:
    status = equalizador_hardening_status(
        enabled=True,
        rate_limit_per_minute=30,
        session_ttl_seconds=900,
        initdata_max_age_seconds=600,
    )

    assert status == {
        "enabled": True,
        "rate_limit_per_minute": 30,
        "session_ttl_seconds": 900,
        "initdata_max_age_seconds": 600,
        "ok": True,
    }
    assert "8505890439" not in repr(status)
    assert "-100" not in repr(status)


def test_phase7_files_wire_hardening_into_router_and_readyz() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    main = (root / "app/main.py").read_text()
    hardening = (root / "app/equalizador/hardening.py").read_text()

    assert "check_equalizador_rate_limit" in router
    assert "validate_equalizador_session" in router
    assert "create_equalizador_session" in router
    assert "mesa_operation_lock" in router
    assert "log_equalizador_event" in router
    assert "equalizador_hardening_status" in main
    assert "def sanitize_ref" in hardening


def test_phase7_rate_limit_buckets_do_not_block_actions() -> None:
    reset_equalizador_rate_limits()
    for idx in range(5):
        check_equalizador_rate_limit(
            operator_ref="usr_AAAAAAAA",
            limit_per_minute=5,
            now=2000.0 + idx,
            bucket="read",
        )

    # Leituras iniciais do painel não consomem o balde das ações.
    result = check_equalizador_rate_limit(
        operator_ref="usr_AAAAAAAA",
        limit_per_minute=1,
        now=2006.0,
        bucket="action",
    )
    assert result["allowed"] is True


def test_phase7_session_is_sliding_when_renewal_is_enabled() -> None:
    reset_equalizador_sessions()
    identity = TelegramWebAppIdentity(user_id=8505890439, user={"id": 8505890439, "first_name": "Piero"}, auth_date=3000)
    session = create_equalizador_session(identity=identity, ttl_seconds=60, now=3000)
    token = str(session["token"])

    assert validate_equalizador_session(token, now=3055, renew_ttl_seconds=60).user_id == 8505890439
    # Sem renovação, a sessão antiga teria expirado em 3060.
    assert validate_equalizador_session(token, now=3100).user_id == 8505890439
