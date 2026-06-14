from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """Raised when Telegram Mini App initData is invalid or expired."""


@dataclass(frozen=True)
class TelegramWebAppIdentity:
    user_id: int
    user: dict[str, object]
    auth_date: int


def _parse_init_data(init_data: str) -> dict[str, str]:
    if not init_data or not init_data.strip():
        raise InitDataError("missing_init_data")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    data: dict[str, str] = {}
    for key, value in pairs:
        data[key] = value
    if "hash" not in data:
        raise InitDataError("missing_hash")
    return data


def _data_check_string(data: Mapping[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(data.items()) if key != "hash")


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> TelegramWebAppIdentity:
    """Validate Telegram Mini App initData on the server.

    This follows Telegram's Web Apps validation flow: remove ``hash``, sort the
    remaining key/value pairs, sign the resulting data_check_string with the
    secret derived from the bot token, compare with constant-time equality, and
    reject stale ``auth_date`` values.
    """
    if not bot_token:
        raise InitDataError("missing_bot_token")
    if max_age_seconds <= 0:
        raise InitDataError("invalid_max_age")

    data = _parse_init_data(init_data)
    received_hash = data.get("hash", "")
    check_string = _data_check_string(data)

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise InitDataError("invalid_hash")

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("invalid_auth_date") from exc
    if auth_date <= 0:
        raise InitDataError("missing_auth_date")

    current_time = int(time.time()) if now is None else int(now)
    if auth_date > current_time + 60:
        raise InitDataError("auth_date_in_future")
    if current_time - auth_date > max_age_seconds:
        raise InitDataError("expired_auth_date")

    try:
        user = json.loads(data.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise InitDataError("invalid_user_json") from exc
    if not isinstance(user, dict):
        raise InitDataError("invalid_user")
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError) as exc:
        raise InitDataError("invalid_user_id") from exc
    if user_id <= 0:
        raise InitDataError("missing_user_id")

    return TelegramWebAppIdentity(user_id=user_id, user=user, auth_date=auth_date)


def extract_tma_authorization(header_value: str | None) -> str:
    """Extract raw initData from ``Authorization: tma <initData>``."""
    if not header_value:
        raise InitDataError("missing_authorization")
    prefix = "tma "
    if not header_value.lower().startswith(prefix):
        raise InitDataError("invalid_authorization_scheme")
    value = header_value[len(prefix) :].strip()
    if not value:
        raise InitDataError("missing_authorization_value")
    return value
