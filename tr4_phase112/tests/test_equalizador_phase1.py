from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.equalizador.identity import display_name_from_telegram_user, make_ui_ref
from app.equalizador.security import InitDataError, extract_tma_authorization, validate_init_data


def _signed_init_data(*, bot_token: str, user_id: int, auth_date: int) -> str:
    data = {
        "auth_date": str(auth_date),
        "query_id": "phase1-test",
        "user": json.dumps({"id": user_id, "first_name": "Piero", "username": "nao_expor"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_equalizador_init_data_validation_accepts_valid_signature():
    token = "123456:test-token"
    init_data = _signed_init_data(bot_token=token, user_id=8505890439, auth_date=1_800_000_000)

    identity = validate_init_data(init_data, bot_token=token, max_age_seconds=600, now=1_800_000_100)

    assert identity.user_id == 8505890439
    assert identity.user["first_name"] == "Piero"


def test_equalizador_init_data_validation_rejects_expired_auth_date():
    token = "123456:test-token"
    init_data = _signed_init_data(bot_token=token, user_id=8505890439, auth_date=1_800_000_000)

    with pytest.raises(InitDataError):
        validate_init_data(init_data, bot_token=token, max_age_seconds=600, now=1_800_001_000)


def test_equalizador_authorization_header_uses_tma_scheme():
    assert extract_tma_authorization("tma abc=1&hash=2") == "abc=1&hash=2"
    with pytest.raises(InitDataError):
        extract_tma_authorization("Bearer abc")


def test_equalizador_ui_ref_does_not_expose_numeric_id():
    ref = make_ui_ref("usr", 8505890439, "secret")
    assert ref.startswith("usr_")
    assert "8505890439" not in ref
    assert display_name_from_telegram_user({"id": 8505890439, "first_name": "Piero", "username": "nao_expor"}) == "Piero"


def test_equalizador_phase1_files_are_read_only_and_conditional():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text()
    router = (root / "app/equalizador/router.py").read_text()
    settings = (root / "app/config/settings.py").read_text()

    assert "TR4_EQUALIZADOR_ENABLED" in settings
    assert "if TR4_EQUALIZADOR_ENABLED:" in main
    assert "app.include_router(equalizador_router)" in main
    assert 'prefix="/equalizador"' in router
    assert 'include_in_schema=False' in router
    assert "initDataUnsafe" not in router
    assert '"user_id"' not in router
    assert '"chat_id"' not in router
    assert '"username"' not in router
