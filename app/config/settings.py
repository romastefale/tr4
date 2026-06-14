from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

# TR3_* names remain supported for deployment compatibility.


def _env(name: str, default: str = "", *, legacy: Iterable[str] = ()) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    for old_name in legacy:
        value = os.getenv(old_name)
        if value is not None:
            return value
    return default


def _int_env(name: str, default: int, *, legacy: Iterable[str] = ()) -> int:
    raw = _env(name, "", legacy=legacy).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("CONFIG_VALUE_IGNORED name=%s expected=int", name)
        return default


def _float_env(name: str, default: float, *, legacy: Iterable[str] = ()) -> float:
    raw = _env(name, "", legacy=legacy).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("CONFIG_VALUE_IGNORED name=%s expected=float", name)
        return default


def _bool_env(name: str, default: bool, *, legacy: Iterable[str] = ()) -> bool:
    value = _env(name, "", legacy=legacy).strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning("CONFIG_VALUE_IGNORED name=%s expected=bool", name)
    return default


def _int_set_env(name: str, *, legacy: Iterable[str] = ()) -> frozenset[int]:
    values: set[int] = set()
    raw_values: list[str] = []
    primary = os.getenv(name)
    if primary is not None:
        raw_values.append(primary)
    for old_name in legacy:
        value = os.getenv(old_name)
        if value is not None:
            raw_values.append(value)
    for raw in raw_values:
        for part in str(raw).replace(";", ",").split(","):
            item = part.strip()
            if not item:
                continue
            try:
                values.add(int(item))
            except ValueError:
                logger.warning("CONFIG_VALUE_IGNORED name=%s expected=int_list", name)
    return frozenset(values)


def _is_sqlite_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("sqlite:")


def _sqlite_or_empty(value: str, *, source: str) -> str:
    if _is_sqlite_url(value):
        return value
    logger.warning("DATABASE_URL_IGNORED source=%s reason=not_sqlite", source)
    return ""


TELEGRAM_BOT_TOKEN = _env(
    "TR3_TELEGRAM_BOT_TOKEN",
    legacy=("TELEGRAM_BOT_TOKEN",),
)


SPOTIFY_CLIENT_ID = _env(
    "TR3_SPOTIFY_CLIENT_ID",
    legacy=("SPOTIFY_CLIENT_ID",),
)
SPOTIFY_CLIENT_SECRET = _env(
    "TR3_SPOTIFY_CLIENT_SECRET",
    legacy=("SPOTIFY_CLIENT_SECRET",),
)

BASE_URL = _env("TR3_BASE_URL", "http://localhost:8000", legacy=("BASE_URL",)).rstrip("/")
SPOTIFY_REDIRECT_URI = f"{BASE_URL}/callback"
SPOTIFY_SCOPES = _env(
    "TR3_SPOTIFY_SCOPES",
    "user-read-currently-playing user-read-recently-played",
    legacy=("SPOTIFY_SCOPES",),
)

SPOTIFY_HTTP_TIMEOUT_SECONDS = _float_env(
    "TR3_SPOTIFY_HTTP_TIMEOUT_SECONDS",
    10.0,
    legacy=("SPOTIFY_HTTP_TIMEOUT_SECONDS",),
)
SPOTIFY_MAX_CONCURRENT_REQUESTS = _int_env(
    "TR3_SPOTIFY_MAX_CONCURRENT_REQUESTS",
    10,
    legacy=("SPOTIFY_MAX_CONCURRENT_REQUESTS",),
)
SPOTIFY_CACHE_TTL_SECONDS = _float_env(
    "TR3_SPOTIFY_CACHE_TTL_SECONDS",
    5.0,
    legacy=("SPOTIFY_CACHE_TTL_SECONDS",),
)
SPOTIFY_CACHE_MAX_ENTRIES = _int_env(
    "TR3_SPOTIFY_CACHE_MAX_ENTRIES",
    500,
    legacy=("SPOTIFY_CACHE_MAX_ENTRIES",),
)
SPOTIFY_PER_USER_RATE_LIMIT = _int_env(
    "TR3_SPOTIFY_PER_USER_RATE_LIMIT",
    10,
    legacy=("SPOTIFY_PER_USER_RATE_LIMIT",),
)
SPOTIFY_RATE_LIMIT_WINDOW_SECONDS = _float_env(
    "TR3_SPOTIFY_RATE_LIMIT_WINDOW_SECONDS",
    5.0,
    legacy=("SPOTIFY_RATE_LIMIT_WINDOW_SECONDS",),
)
SPOTIFY_CIRCUIT_BREAKER_THRESHOLD = _int_env(
    "TR3_SPOTIFY_CIRCUIT_BREAKER_THRESHOLD",
    3,
    legacy=("SPOTIFY_CIRCUIT_BREAKER_THRESHOLD",),
)
SPOTIFY_CIRCUIT_BREAKER_COOLDOWN_SECONDS = _float_env(
    "TR3_SPOTIFY_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
    8.0,
    legacy=("SPOTIFY_CIRCUIT_BREAKER_COOLDOWN_SECONDS",),
)
SPOTIFY_CANVAS_ENABLED = _bool_env(
    "TR3_SPOTIFY_CANVAS_ENABLED",
    True,
    legacy=("SPOTIFY_CANVAS_ENABLED",),
)
SPOTIFY_CANVAS_SP_DC = _env(
    "TR3_SPOTIFY_CANVAS_SP_DC",
    legacy=("SPOTIFY_CANVAS_SP_DC",),
).strip()
SPOTIFY_CANVAS_TIMEOUT_SECONDS = _float_env(
    "TR3_SPOTIFY_CANVAS_TIMEOUT_SECONDS",
    4.0,
    legacy=("SPOTIFY_CANVAS_TIMEOUT_SECONDS",),
)

CANVAS_CACHE_ENABLED = _bool_env(
    "TR3_CANVAS_CACHE_ENABLED",
    True,
    legacy=("CANVAS_CACHE_ENABLED",),
)
CANVAS_CACHE_CHANNEL_ID = _int_env(
    "TR3_CANVAS_CACHE_CHANNEL_ID",
    0,
    legacy=("CANVAS_CACHE_CHANNEL_ID",),
)

LASTFM_API_KEY = _env(
    "TR3_LASTFM_API_KEY",
    legacy=("LASTFM_API_KEY",),
)
LASTFM_API_BASE_URL = _env(
    "TR3_LASTFM_API_BASE_URL",
    "https://ws.audioscrobbler.com/2.0/",
    legacy=("LASTFM_API_BASE_URL",),
)
HTTP_TIMEOUT_SECONDS = _float_env(
    "TR3_HTTP_TIMEOUT_SECONDS",
    SPOTIFY_HTTP_TIMEOUT_SECONDS,
    legacy=("HTTP_TIMEOUT_SECONDS",),
)

def _resolve_data_dir() -> Path:
    raw = _env("TR3_DATA_DIR", "/data", legacy=("DATA_DIR",)).strip() or "/data"
    candidates = [Path(raw), Path("/app/data"), Path("/tmp/tr4-data")]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            logger.warning("DATA_DIR_UNAVAILABLE path=%s", candidate)
    fallback = Path("/tmp/tr4-data")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = _resolve_data_dir()


def _database_url() -> str:
    explicit = os.getenv("TR3_DATABASE_URL")
    if explicit is not None and explicit.strip():
        sqlite_url = _sqlite_or_empty(explicit.strip(), source="TR3_DATABASE_URL")
        if sqlite_url:
            return sqlite_url

    legacy = os.getenv("DATABASE_URL")
    if legacy is not None and legacy.strip():
        sqlite_url = _sqlite_or_empty(legacy.strip(), source="DATABASE_URL")
        if sqlite_url:
            return sqlite_url

    return f"sqlite:///{DATA_DIR / 'app.db'}"


DATABASE_URL = _database_url()

CODE_OWNER_IDS = _int_set_env(
    "TR4_CODE_OWNER_IDS",
    legacy=("CODE_OWNER_IDS", "TR3_OWNER_IDS", "OWNER_IDS", "TR3_OWNER_ID", "OWNER_ID"),
)


def is_code_owner(user_id: int | str | None) -> bool:
    try:
        parsed = int(user_id)
    except Exception:
        return False
    return parsed in CODE_OWNER_IDS

# Music-only runtime keeps only command rate limits and music services.

COMMAND_RATE_LIMIT_ENABLED = _bool_env(
    "TR3_COMMAND_RATE_LIMIT_ENABLED",
    True,
    legacy=("COMMAND_RATE_LIMIT_ENABLED",),
)
COMMAND_RATE_LIMIT_WINDOW_SECONDS = _int_env(
    "TR3_COMMAND_RATE_LIMIT_WINDOW_SECONDS",
    60,
    legacy=("COMMAND_RATE_LIMIT_WINDOW_SECONDS",),
)
COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW = _int_env(
    "TR3_COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW",
    6,
    legacy=("COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW",),
)
COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW = _int_env(
    "TR3_COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW",
    20,
    legacy=("COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW",),
)


RADIO_SCHEDULER_ENABLED = _bool_env(
    "TR3_RADIO_SCHEDULER_ENABLED",
    True,
    legacy=("RADIO_SCHEDULER_ENABLED",),
)
RADIO_SCHEDULER_INTERVAL_SECONDS = _int_env(
    "TR3_RADIO_SCHEDULER_INTERVAL_SECONDS",
    60,
    legacy=("RADIO_SCHEDULER_INTERVAL_SECONDS",),
)
RADIO_SCHEDULER_MAX_DUE_PER_TICK = _int_env(
    "TR3_RADIO_SCHEDULER_MAX_DUE_PER_TICK",
    10,
    legacy=("RADIO_SCHEDULER_MAX_DUE_PER_TICK",),
)

SESSION_PERSISTENCE_ENABLED = _bool_env(
    "TR3_SESSION_PERSISTENCE_ENABLED",
    True,
    legacy=("SESSION_PERSISTENCE_ENABLED",),
)
OPERATIONAL_LOCK_TTL_SECONDS = _int_env(
    "TR3_OPERATIONAL_LOCK_TTL_SECONDS",
    90,
    legacy=("OPERATIONAL_LOCK_TTL_SECONDS",),
)

REQUIRED_ENV_VARS = (
    ("TR3_TELEGRAM_BOT_TOKEN/TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("TR3_SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_ID", SPOTIFY_CLIENT_ID),
    ("TR3_SPOTIFY_CLIENT_SECRET/SPOTIFY_CLIENT_SECRET", SPOTIFY_CLIENT_SECRET),
    ("TR3_LASTFM_API_KEY/LASTFM_API_KEY", LASTFM_API_KEY),
    (
        "TR3_BASE_URL/BASE_URL",
        BASE_URL if BASE_URL != "http://localhost:8000" else "",
    ),
)


def validate_required_env() -> list[str]:
    return [name for name, value in REQUIRED_ENV_VARS if not value]


_WEBHOOK_SECRET_PURPOSE = b"tr3-webhook-v1"


def telegram_webhook_secret() -> str | None:
    if not TELEGRAM_BOT_TOKEN:
        return None
    return hmac.new(
        TELEGRAM_BOT_TOKEN.encode(),
        _WEBHOOK_SECRET_PURPOSE,
        hashlib.sha256,
    ).hexdigest()
