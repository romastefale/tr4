from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[2]

# TR3_* names are the canonical server variables from Phase 1 onward.
# Legacy names remain supported so the current deployment can migrate
# without changing every Railway/Replit variable at once.


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
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer environment variable {name}={raw!r}") from exc


def _float_env(name: str, default: float, *, legacy: Iterable[str] = ()) -> float:
    raw = _env(name, "", legacy=legacy).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid float environment variable {name}={raw!r}") from exc


def _bool_env(name: str, default: bool, *, legacy: Iterable[str] = ()) -> bool:
    value = _env(name, "", legacy=legacy).strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean environment variable {name}={value!r}")


def _int_list_env(name: str, *, legacy: Iterable[str] = ()) -> tuple[int, ...]:
    raw = _env(name, "", legacy=legacy).strip()
    if not raw:
        return ()
    items: list[int] = []
    for part in raw.replace(";", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            items.append(int(value))
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid integer list environment variable {name}: item {value!r}"
            ) from exc
    return tuple(dict.fromkeys(items))


def _choice_env(
    name: str,
    default: str,
    choices: set[str],
    *,
    legacy: Iterable[str] = (),
) -> str:
    value = _env(name, default, legacy=legacy).strip().lower()
    if value not in choices:
        raise RuntimeError(
            f"Invalid environment variable {name}={value!r}; expected one of {sorted(choices)}"
        )
    return value


def _is_sqlite_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("sqlite:")


def _require_sqlite_url(value: str) -> str:
    if not _is_sqlite_url(value):
        raise RuntimeError(
            "TR3 is configured as SQLite-only. Set TR3_DATABASE_URL/DATABASE_URL "
            "to a sqlite URL such as sqlite:////data/app.db."
        )
    return value


TELEGRAM_BOT_TOKEN = _env(
    "TR3_TELEGRAM_BOT_TOKEN",
    legacy=("TELEGRAM_BOT_TOKEN",),
)

OWNER_ID = _int_env(
    "TR3_ROOT_USER_ID",
    0,
    legacy=("TR3_OWNER_ID", "OWNER_ID"),
)
ROOT_USER_ID = OWNER_ID

SECOND_MODERATOR_ID = _int_env(
    "TR3_SECOND_MODERATOR_ID",
    0,
    legacy=("SECOND_MODERATOR_ID",),
)
THIRD_MODERATOR_ID = _int_env(
    "TR3_THIRD_MODERATOR_ID",
    0,
    legacy=("THIRD_MODERATOR_ID",),
)
MODERATOR_IDS: tuple[int, ...] = tuple(
    x for x in (OWNER_ID, SECOND_MODERATOR_ID, THIRD_MODERATOR_ID) if x
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

DATA_DIR = Path(_env("TR3_DATA_DIR", "/app/data", legacy=("DATA_DIR",)))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _database_url() -> str:
    """Return a SQLite URL without crashing on Railway's legacy DATABASE_URL.

    Music-only TR4 is SQLite-only. Railway projects migrated from older TR3
    deployments may still have a Postgres DATABASE_URL injected by a previous
    database plugin. Treat TR3_DATABASE_URL as explicit and strict, but ignore a
    non-SQLite legacy DATABASE_URL so the app can boot with the local/volume
    SQLite path.
    """
    explicit = os.getenv("TR3_DATABASE_URL")
    if explicit is not None and explicit.strip():
        return _require_sqlite_url(explicit.strip())

    legacy = os.getenv("DATABASE_URL")
    if legacy is not None and legacy.strip() and _is_sqlite_url(legacy):
        return legacy.strip()

    return f"sqlite:///{DATA_DIR / 'app.db'}"


DATABASE_URL = _database_url()

# Phase 1 server variables reserved for upcoming managed-groups/security phases.
TIGRAORESPONDE_TARGET_CHAT_ID = _int_env(
    "TR3_TIGRAORESPONDE_TARGET_CHAT_ID",
    0,
    legacy=("TIGRAORESPONDE_TARGET_CHAT_ID",),
)
SECURITY_ALERT_CHAT_ID = _int_env(
    "TR3_SECURITY_ALERT_CHAT_ID",
    OWNER_ID,
    legacy=("SECURITY_ALERT_CHAT_ID",),
)
AUDIT_LOG_CHAT_ID = _int_env(
    "TR3_AUDIT_LOG_CHAT_ID",
    SECURITY_ALERT_CHAT_ID,
    legacy=("AUDIT_LOG_CHAT_ID",),
)
MANAGED_GROUP_IDS = _int_list_env(
    "TR3_MANAGED_GROUP_IDS",
    legacy=("MANAGED_GROUP_IDS",),
)
PANIC_MODE = _choice_env(
    "TR3_PANIC_MODE",
    "normal",
    {"normal", "alert", "restricted", "panic_stop"},
    legacy=("PANIC_MODE",),
)
PANIC_STOP_SERVER = _bool_env(
    "TR3_PANIC_STOP_SERVER",
    False,
    legacy=("PANIC_STOP_SERVER",),
)
SECURITY_MONITOR_ENABLED = _bool_env(
    "TR3_SECURITY_MONITOR_ENABLED",
    True,
    legacy=("SECURITY_MONITOR_ENABLED",),
)
SECURITY_MONITOR_INTERVAL_SECONDS = _int_env(
    "TR3_SECURITY_MONITOR_INTERVAL_SECONDS",
    300,
    legacy=("SECURITY_MONITOR_INTERVAL_SECONDS",),
)
SECURITY_MONITOR_MAX_GROUPS = _int_env(
    "TR3_SECURITY_MONITOR_MAX_GROUPS",
    50,
    legacy=("SECURITY_MONITOR_MAX_GROUPS",),
)
ANOMALY_WINDOW_SECONDS = _int_env(
    "TR3_ANOMALY_WINDOW_SECONDS",
    300,
    legacy=("ANOMALY_WINDOW_SECONDS",),
)
ANOMALY_MAX_FORBIDDEN_WEBHOOKS = _int_env(
    "TR3_ANOMALY_MAX_FORBIDDEN_WEBHOOKS",
    5,
    legacy=("ANOMALY_MAX_FORBIDDEN_WEBHOOKS",),
)
ANOMALY_MAX_PERMISSION_DENIED = _int_env(
    "TR3_ANOMALY_MAX_PERMISSION_DENIED",
    10,
    legacy=("ANOMALY_MAX_PERMISSION_DENIED",),
)

# Phase 7 security panel/alert/rate-limit settings.
SECURITY_ALERTS_ENABLED = _bool_env(
    "TR3_SECURITY_ALERTS_ENABLED",
    True,
    legacy=("SECURITY_ALERTS_ENABLED",),
)
SECURITY_AUDIT_VIEW_LIMIT = _int_env(
    "TR3_SECURITY_AUDIT_VIEW_LIMIT",
    10,
    legacy=("SECURITY_AUDIT_VIEW_LIMIT",),
)
AUDIT_EXPORT_LIMIT = _int_env(
    "TR3_AUDIT_EXPORT_LIMIT",
    1000,
    legacy=("AUDIT_EXPORT_LIMIT",),
)
AUDIT_RETENTION_DAYS = _int_env(
    "TR3_AUDIT_RETENTION_DAYS",
    90,
    legacy=("AUDIT_RETENTION_DAYS",),
)
CRITICAL_OPERATION_EXPORT_LIMIT = _int_env(
    "TR3_CRITICAL_OPERATION_EXPORT_LIMIT",
    1000,
    legacy=("CRITICAL_OPERATION_EXPORT_LIMIT",),
)
CRITICAL_OPERATION_RETENTION_DAYS = _int_env(
    "TR3_CRITICAL_OPERATION_RETENTION_DAYS",
    180,
    legacy=("CRITICAL_OPERATION_RETENTION_DAYS",),
)
AUDIT_EXPORT_ENCRYPTION_KEY = _env(
    "TR3_AUDIT_EXPORT_ENCRYPTION_KEY",
    legacy=("AUDIT_EXPORT_ENCRYPTION_KEY",),
)
AUDIT_EXPORT_ENCRYPTION_KEY_ID = _env(
    "TR3_AUDIT_EXPORT_ENCRYPTION_KEY_ID",
    "current",
    legacy=("AUDIT_EXPORT_ENCRYPTION_KEY_ID",),
)
AUDIT_EXPORT_DECRYPTION_KEYS = _env(
    "TR3_AUDIT_EXPORT_DECRYPTION_KEYS",
    legacy=("AUDIT_EXPORT_DECRYPTION_KEYS",),
)

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
    ("TR3_ROOT_USER_ID/OWNER_ID", str(OWNER_ID) if OWNER_ID else ""),
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
