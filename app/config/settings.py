from __future__ import annotations

import hashlib
import hmac
import json
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




def _int_set_env(name: str, default: str = "", *, legacy: Iterable[str] = ()) -> set[int]:
    raw = _env(name, default, legacy=legacy).strip()
    if not raw:
        return set()
    values: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError as exc:
            raise RuntimeError(f"Invalid integer item in environment variable {name}={token!r}") from exc
    return values


_EQUALIZADOR_CONFIG_ERRORS: list[str] = []


def _record_equalizador_config_error(message: str) -> None:
    _EQUALIZADOR_CONFIG_ERRORS.append(message[:200])


def _equalizador_bool_env(name: str, default: bool) -> bool:
    try:
        return _bool_env(name, default)
    except RuntimeError as exc:
        _record_equalizador_config_error(str(exc))
        return default


def _equalizador_int_env(name: str, default: int) -> int:
    try:
        return _int_env(name, default)
    except RuntimeError as exc:
        _record_equalizador_config_error(str(exc))
        return default


def _equalizador_int_set_env(name: str) -> set[int]:
    raw = _env(name, "").strip()
    if not raw:
        return set()
    values: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError:
            _record_equalizador_config_error(f"Invalid integer item in environment variable {name}={token!r}")
    return values



def _json_int_mapping_env(name: str) -> dict[str, int]:
    raw = _env(name, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    mapping: dict[str, int] = {}
    for key, value in data.items():
        label = str(key or "").strip()
        if not label:
            continue
        try:
            mapping[label] = int(value)
        except (TypeError, ValueError):
            continue
    return mapping

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

def _path_is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".tr4_persistence_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _data_dir() -> Path:
    """Return the runtime data directory, with /data as production truth.

    Railway mounts the persistent volume at /data for this service. Earlier
    deployments could still carry DATA_DIR=/app/data or a host-like
    RAILWAY_VOLUME_MOUNT_PATH value, causing SQLite to use the ephemeral
    container directory. The production rule is therefore explicit:

    * if /data is writable, use /data;
    * an explicit TR3_DATA_DIR/DATA_DIR is honored only when /data is not
      writable or the explicit path itself points under /data;
    * /app/data remains a local-development fallback only.
    """
    explicit = _env("TR3_DATA_DIR", "", legacy=("DATA_DIR",)).strip()
    data_path = Path("/data")
    data_writable = _path_is_writable_dir(data_path)
    if data_writable:
        if explicit and str(Path(explicit)).startswith("/data"):
            return Path(explicit)
        return data_path
    if explicit:
        return Path(explicit)
    railway_volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_volume and _path_is_writable_dir(Path(railway_volume)):
        return Path(railway_volume)
    return Path("/app/data")


DATA_DIR = _data_dir()
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


GROUP_ALIASES = _json_int_mapping_env("GROUP_ALIASES")

def group_aliases() -> dict[str, int]:
    return dict(GROUP_ALIASES)

def group_alias_for_chat(chat_id: int) -> str | None:
    for label, configured_chat_id in GROUP_ALIASES.items():
        if int(configured_chat_id) == int(chat_id):
            return label
    return None

# Equalizador Mini App — disabled by default. These variables are parsed in
# failure-tolerant mode so a bad Equalizador value never prevents /healthz from
# coming up. Invalid items are reported through equalizador_config_errors() and
# /readyz, matching the release rule that Equalizador failures must not kill the
# musical TR4 process.
TR4_EQUALIZADOR_ENABLED = _equalizador_bool_env("TR4_EQUALIZADOR_ENABLED", False)
TR4_EQUALIZADOR_APP_NAME = _env("TR4_EQUALIZADOR_APP_NAME", "equalizador").strip() or "equalizador"
TR4_EQUALIZADOR_MAESTRO_IDS_SET = _equalizador_int_set_env("TR4_EQUALIZADOR_MAESTRO_IDS")
TR4_EQUALIZADOR_OPERADOR_IDS_SET = _equalizador_int_set_env("TR4_EQUALIZADOR_OPERADOR_IDS")
TR4_EQUALIZADOR_PALCO_IDS_SET = _equalizador_int_set_env("TR4_EQUALIZADOR_PALCO_IDS")
TR4_EQUALIZADOR_CANAIS_RAW = _env("TR4_EQUALIZADOR_CANAIS", "")
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS = _equalizador_bool_env("TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS", True)
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS = _equalizador_int_env("TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS", 600)
TR4_EQUALIZADOR_SESSION_TTL_SECONDS = _equalizador_int_env("TR4_EQUALIZADOR_SESSION_TTL_SECONDS", 28800)
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE = _equalizador_int_env("TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE", 120)
TR4_MUSIC_REACTIONS_ENABLED = _bool_env("TR4_MUSIC_REACTIONS_ENABLED", False, legacy=("MUSIC_REACTIONS_ENABLED",))
TR4_MUSIC_LEGACY_LIKES_DISPLAY_ENABLED = _bool_env("TR4_MUSIC_LEGACY_LIKES_DISPLAY_ENABLED", False, legacy=("MUSIC_LEGACY_LIKES_DISPLAY_ENABLED",))


def equalizador_user_is_allowed(user_id: int) -> bool:
    return user_id in TR4_EQUALIZADOR_MAESTRO_IDS_SET or user_id in TR4_EQUALIZADOR_OPERADOR_IDS_SET


def equalizador_allowed_palco_ids() -> set[int]:
    return set(TR4_EQUALIZADOR_PALCO_IDS_SET)


def equalizador_canais_raw() -> str:
    return TR4_EQUALIZADOR_CANAIS_RAW


def equalizador_config_errors() -> tuple[str, ...]:
    return tuple(_EQUALIZADOR_CONFIG_ERRORS)


def equalizador_config_ok() -> bool:
    return not _EQUALIZADOR_CONFIG_ERRORS


def equalizador_alias_secret() -> str:
    # Validation requires TELEGRAM_BOT_TOKEN. Reuse it as a server-side secret
    # for stable UI aliases without exposing Telegram numeric identifiers.
    if TELEGRAM_BOT_TOKEN:
        return TELEGRAM_BOT_TOKEN
    return "tr4-equalizador-alias-development-only"


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
