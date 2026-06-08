from __future__ import annotations

from pathlib import Path
import sys
import types

from app.equalizador.hardening import (
    create_equalizador_session,
    reset_equalizador_sessions,
    validate_equalizador_session,
)
from app.equalizador.security import TelegramWebAppIdentity


def test_phase138_4_equalizador_session_survives_backend_restart_and_expired_grace(monkeypatch) -> None:
    persisted: dict[str, tuple[TelegramWebAppIdentity, int, int]] = {}

    def fake_save_session(*, token, identity, issued_at, expires_at, db_engine=None):
        persisted[str(token)] = (identity, int(issued_at), int(expires_at))

    def fake_load_session(token, *, db_engine=None):
        return persisted.get(str(token))

    def fake_delete_session(token, *, db_engine=None):
        persisted.pop(str(token), None)

    fake_module = types.ModuleType("app.equalizador.session_store")
    fake_module.save_session = fake_save_session
    fake_module.load_session = fake_load_session
    fake_module.delete_session = fake_delete_session
    monkeypatch.setitem(sys.modules, "app.equalizador.session_store", fake_module)

    reset_equalizador_sessions()
    identity = TelegramWebAppIdentity(user_id=8505890439, user={"id": 8505890439, "first_name": "Piero"}, auth_date=1000)
    session = create_equalizador_session(identity=identity, ttl_seconds=10, now=1000)
    token = str(session["token"])
    assert token in persisted

    # Simula deploy/restart: a memória do processo some, mas o banco persistente mantém o token.
    reset_equalizador_sessions()
    restored = validate_equalizador_session(
        token,
        now=1012,
        renew_ttl_seconds=100,
        expired_grace_seconds=3600,
    )

    assert restored.user_id == 8505890439
    assert persisted[token][2] == 1112

    # Depois da renovação, outro restart continua aceitando a mesma sessão.
    reset_equalizador_sessions()
    assert validate_equalizador_session(token, now=1050).user_id == 8505890439


def test_phase138_4_router_uses_persistent_session_grace_and_local_storage() -> None:
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    settings = Path("app/config/settings.py").read_text(encoding="utf-8")
    session_store_text = Path("app/equalizador/session_store.py").read_text(encoding="utf-8")

    assert 'TR4_EQUALIZADOR_SESSION_TTL_SECONDS = _equalizador_int_env("TR4_EQUALIZADOR_SESSION_TTL_SECONDS", 2592000)' in settings
    assert 'TR4_EQUALIZADOR_SESSION_GRACE_SECONDS = _equalizador_int_env("TR4_EQUALIZADOR_SESSION_GRACE_SECONDS", 7776000)' in settings
    assert "expired_grace_seconds=settings.TR4_EQUALIZADOR_SESSION_GRACE_SECONDS" in text
    assert 'localStorage.setItem(SESSION_KEY, value)' in text
    assert 'localStorage.setItem("tr4_public_eqs", value)' in text
    assert 'sessionStorage.getItem(SESSION_KEY) || localStorage.getItem("tr4_public_eqs") || localStorage.getItem(SESSION_KEY)' in text
    assert "def cleanup_expired_sessions(*, now_ts: int, db_engine: Engine = default_engine, grace_seconds: int = 0)" in session_store_text
