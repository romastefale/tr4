from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

from app.config.settings import TELEGRAM_BOT_TOKEN

_WEBAPP_AUTH_MAX_AGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class WebMusicUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    language_code: str | None = None

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name or ""]
        return " ".join(p for p in parts if p).strip() or "Usuário"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "username": self.username,
            "photo_url": self.photo_url,
            "language_code": self.language_code,
        }


def _unauthorized(code: str = "webapp_auth_required") -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code, "message": "Sessão Telegram inválida ou ausente."})


def _validate_tma_init_data(init_data: str) -> WebMusicUser:
    if not TELEGRAM_BOT_TOKEN:
        raise _unauthorized("bot_token_missing")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    if not pairs:
        raise _unauthorized("empty_init_data")
    values: dict[str, str] = {key: value for key, value in pairs}
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise _unauthorized("hash_missing")
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise _unauthorized("hash_mismatch")
    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError:
        raise _unauthorized("auth_date_invalid")
    if auth_date <= 0 or time.time() - auth_date > _WEBAPP_AUTH_MAX_AGE_SECONDS:
        raise _unauthorized("auth_date_expired")
    raw_user = values.get("user", "")
    if not raw_user:
        raise _unauthorized("user_missing")
    try:
        user_data = json.loads(raw_user)
    except json.JSONDecodeError:
        raise _unauthorized("user_invalid_json")
    try:
        user_id = int(user_data["id"])
    except Exception:
        raise _unauthorized("user_id_invalid")
    first_name = str(user_data.get("first_name") or "Usuário")
    return WebMusicUser(
        id=user_id,
        first_name=first_name,
        last_name=user_data.get("last_name"),
        username=user_data.get("username"),
        photo_url=user_data.get("photo_url"),
        language_code=user_data.get("language_code"),
    )


def authenticate_web_music_request(request: Request) -> WebMusicUser:
    header = request.headers.get("Authorization", "").strip()
    if not header:
        raise _unauthorized()
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "tma" or not value.strip():
        # O fallback histórico "eqs" foi recusado nesta integração musical limpa.
        raise _unauthorized("tma_required")
    return _validate_tma_init_data(value.strip())
