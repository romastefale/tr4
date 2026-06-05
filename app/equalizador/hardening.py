from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from app.equalizador.security import TelegramWebAppIdentity

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^(usr|grp|msg|his|exp)_[A-Z0-9]{6,32}$")
_ACTION_RE = re.compile(r"^[a-z]+(?:\.[a-z]+)*(?:_[a-z]+)?$")


class EqualizadorRateLimitError(RuntimeError):
    """Raised when an Equalizador operator exceeds the configured rate."""


class EqualizadorSessionError(RuntimeError):
    """Raised when an Equalizador short session is missing or expired."""


class EqualizadorMesaBusyError(RuntimeError):
    """Raised when a palco/action lock is already held."""


@dataclass(frozen=True)
class EqualizadorSession:
    token: str
    identity: TelegramWebAppIdentity
    expires_at: int
    issued_at: int


_rate_windows: dict[str, list[float]] = {}
_sessions: dict[str, EqualizadorSession] = {}
_mesa_locks: dict[str, asyncio.Lock] = {}


def _now_ts(now: float | None = None) -> float:
    return time.time() if now is None else float(now)


def _iso_from_ts(ts: int | float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def sanitize_ref(value: object, *, fallback: str = "ref_oculta") -> str:
    """Return only Equalizador UI refs for public logs.

    If a raw Telegram identifier accidentally reaches this helper, it is not
    logged. Logs keep enough correlation through aliases without exposing IDs.
    """
    text = str(value or "").strip()
    return text if _REF_RE.match(text) else fallback


def sanitize_action(value: object, *, fallback: str = "ajuste") -> str:
    text = str(value or "").strip().lower()
    return text if _ACTION_RE.match(text) and "@" not in text else fallback


def log_equalizador_event(event: str, *, ator_ref: object, palco_ref: object | None = None, ajuste: object | None = None) -> None:
    """Emit sanitized Equalizador operational logs.

    No raw Telegram user_id, chat_id, message_id, username or payload is logged.
    """
    safe_event = str(event or "EQUALIZADOR_EVENTO").strip().upper().replace(" ", "_")[:80]
    safe_actor = sanitize_ref(ator_ref)
    safe_palco = sanitize_ref(palco_ref, fallback="-") if palco_ref is not None else "-"
    safe_ajuste = sanitize_action(ajuste, fallback="-") if ajuste is not None else "-"
    logger.info("%s | ator=%s | palco=%s | ajuste=%s", safe_event, safe_actor, safe_palco, safe_ajuste)


def check_equalizador_rate_limit(*, operator_ref: str, limit_per_minute: int, now: float | None = None) -> dict[str, object]:
    """Apply an in-memory fixed-window rate limit per sanitized operator ref."""
    if limit_per_minute <= 0:
        return {"allowed": True, "remaining": None, "reset_at": None}
    key = sanitize_ref(operator_ref)
    current = _now_ts(now)
    window_start = current - 60.0
    hits = [stamp for stamp in _rate_windows.get(key, []) if stamp > window_start]
    if len(hits) >= int(limit_per_minute):
        _rate_windows[key] = hits
        reset_at = int(min(hits) + 60.0)
        raise EqualizadorRateLimitError(_iso_from_ts(reset_at))
    hits.append(current)
    _rate_windows[key] = hits
    remaining = max(0, int(limit_per_minute) - len(hits))
    reset_at = int((min(hits) if hits else current) + 60.0)
    return {"allowed": True, "remaining": remaining, "reset_at": _iso_from_ts(reset_at)}


def reset_equalizador_rate_limits() -> None:
    _rate_windows.clear()


def create_equalizador_session(
    *,
    identity: TelegramWebAppIdentity,
    ttl_seconds: int,
    now: float | None = None,
) -> dict[str, object]:
    """Create a short opaque session token that contains no Telegram ID."""
    if ttl_seconds <= 0:
        raise EqualizadorSessionError("session_ttl_invalido")
    issued_at = int(_now_ts(now))
    expires_at = issued_at + int(ttl_seconds)
    token = secrets.token_urlsafe(32)
    _sessions[token] = EqualizadorSession(token=token, identity=identity, issued_at=issued_at, expires_at=expires_at)
    try:
        from app.equalizador.session_store import save_session

        save_session(token=token, identity=identity, issued_at=issued_at, expires_at=expires_at)
    except Exception:
        logger.debug("equalizador_session_store_save_failed", exc_info=True)
    return {
        "token": token,
        "expira_em": _iso_from_ts(expires_at),
        "ttl_segundos": int(ttl_seconds),
    }


def validate_equalizador_session(token: str, *, now: float | None = None) -> TelegramWebAppIdentity:
    value = str(token or "").strip()
    if not value:
        raise EqualizadorSessionError("session_missing")
    session = _sessions.get(value)
    current = int(_now_ts(now))
    if not session:
        try:
            from app.equalizador.session_store import load_session

            loaded = load_session(value)
        except Exception:
            loaded = None
        if not loaded:
            raise EqualizadorSessionError("session_not_found")
        identity, issued_at, expires_at = loaded
        session = EqualizadorSession(token=value, identity=identity, issued_at=issued_at, expires_at=expires_at)
        _sessions[value] = session
    if session.expires_at <= current:
        _sessions.pop(value, None)
        try:
            from app.equalizador.session_store import delete_session

            delete_session(value)
        except Exception:
            logger.debug("equalizador_session_store_delete_failed", exc_info=True)
        raise EqualizadorSessionError("session_expired")
    return session.identity


def reset_equalizador_sessions() -> None:
    _sessions.clear()


@asynccontextmanager
async def mesa_operation_lock(lock_key: str, *, timeout_seconds: float = 0.05) -> AsyncIterator[None]:
    """Prevent concurrent Equalizador actions over the same palco/action key."""
    key = str(lock_key or "mesa").strip()[:120]
    lock = _mesa_locks.setdefault(key, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=max(0.001, float(timeout_seconds)))
    except asyncio.TimeoutError as exc:
        raise EqualizadorMesaBusyError("mesa_ocupada") from exc
    try:
        yield
    finally:
        lock.release()


def reset_equalizador_locks() -> None:
    _mesa_locks.clear()


def equalizador_hardening_status(
    *,
    enabled: bool,
    rate_limit_per_minute: int,
    session_ttl_seconds: int,
    initdata_max_age_seconds: int,
) -> dict[str, object]:
    """Return readiness-safe hardening metadata without secrets or IDs."""
    checks = {
        "enabled": bool(enabled),
        "rate_limit_per_minute": int(rate_limit_per_minute),
        "session_ttl_seconds": int(session_ttl_seconds),
        "initdata_max_age_seconds": int(initdata_max_age_seconds),
    }
    checks["ok"] = (not enabled) or (
        int(rate_limit_per_minute) >= 0 and int(session_ttl_seconds) > 0 and int(initdata_max_age_seconds) > 0
    )
    return checks
