from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque

from app.config.settings import (
    ANOMALY_MAX_FORBIDDEN_WEBHOOKS,
    ANOMALY_MAX_PERMISSION_DENIED,
    ANOMALY_WINDOW_SECONDS,
    PANIC_MODE,
    PANIC_STOP_SERVER,
    OPERATIONAL_LOCK_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

from app.security.session_store import acquire_operational_lock, release_operational_lock

_ALLOWED_MODES = {"normal", "alert", "restricted", "panic_stop"}
_RUNTIME_MODE = PANIC_MODE if PANIC_MODE in _ALLOWED_MODES else "normal"
_MODE_REASON: str | None = None
_SIGNALS: dict[str, Deque[datetime]] = defaultdict(deque)


class PanicStopRequested(RuntimeError):
    """Raised only when panic_stop is explicitly configured to stop server."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_security_mode() -> str:
    return _RUNTIME_MODE


def get_security_reason() -> str | None:
    return _MODE_REASON


def _set_security_mode_unlocked(mode: str, *, reason: str | None = None) -> str:
    global _RUNTIME_MODE, _MODE_REASON
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"invalid security mode: {mode!r}")
    old = _RUNTIME_MODE
    _RUNTIME_MODE = mode
    _MODE_REASON = reason
    logger.warning("SECURITY_MODE_CHANGED | old=%s | new=%s | reason=%s", old, mode, reason or "-")
    try:
        from app.security.audit import log_audit_event

        log_audit_event(
            category="security",
            action="mode_changed",
            status="success",
            reason=reason,
            payload={"old": old, "new": mode},
        )
    except Exception:
        logger.debug("SECURITY_MODE_AUDIT_FAILED", exc_info=True)
    if mode == "panic_stop" and PANIC_STOP_SERVER:
        raise PanicStopRequested(reason or "panic_stop requested")
    return _RUNTIME_MODE


def set_security_mode(mode: str, *, reason: str | None = None) -> str:
    lock = acquire_operational_lock(
        "security_mode",
        ttl_seconds=OPERATIONAL_LOCK_TTL_SECONDS,
        metadata={"mode": mode, "reason": reason},
    )
    if not lock.acquired:
        try:
            from app.security.audit import log_audit_event

            log_audit_event(
                category="security",
                action="mode_change_lock_busy",
                status="blocked",
                reason=reason,
                payload={"requested_mode": mode, "lock_owner": lock.owner, "expires_at": lock.expires_at},
            )
        except Exception:
            logger.debug("SECURITY_MODE_LOCK_AUDIT_FAILED", exc_info=True)
        raise RuntimeError("security mode change already in progress")
    try:
        return _set_security_mode_unlocked(mode, reason=reason)
    finally:
        release_operational_lock("security_mode", owner=lock.owner)


def is_restricted() -> bool:
    return _RUNTIME_MODE in {"restricted", "panic_stop"}


def is_panic_stop() -> bool:
    return _RUNTIME_MODE == "panic_stop"


def should_block_delegate_actions(actor_is_root: bool) -> bool:
    return is_restricted() and not actor_is_root


def should_block_automations() -> bool:
    return is_restricted()


def record_security_signal(name: str, *, threshold: int | None = None, reason: str | None = None) -> int:
    """Record a security signal and escalate to alert/restricted if threshold hits.

    This is intentionally in-memory for Phase 6. Audit persistence records the
    escalation; later phases can persist counters if needed.
    """
    now = utcnow()
    window = timedelta(seconds=max(1, ANOMALY_WINDOW_SECONDS))
    q = _SIGNALS[name]
    q.append(now)
    while q and now - q[0] > window:
        q.popleft()
    count = len(q)
    effective_threshold = threshold
    if effective_threshold is None:
        if name == "webhook.invalid_secret":
            effective_threshold = ANOMALY_MAX_FORBIDDEN_WEBHOOKS
        elif name == "permission.denied":
            effective_threshold = ANOMALY_MAX_PERMISSION_DENIED
        else:
            effective_threshold = 0
    logger.warning("SECURITY_SIGNAL | name=%s | count=%s | threshold=%s | reason=%s", name, count, effective_threshold, reason or "-")
    if effective_threshold and count >= effective_threshold and _RUNTIME_MODE == "normal":
        set_security_mode("alert", reason=reason or f"security signal threshold hit: {name}")
    return count


def reset_security_signals() -> None:
    _SIGNALS.clear()


def security_status() -> dict[str, object]:
    return {
        "mode": _RUNTIME_MODE,
        "reason": _MODE_REASON,
        "panic_stop_server": PANIC_STOP_SERVER,
        "signals": {name: len(values) for name, values in _SIGNALS.items()},
    }
