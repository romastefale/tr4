from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque

from app.config.settings import (
    COMMAND_RATE_LIMIT_ENABLED,
    COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW,
    COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW,
    COMMAND_RATE_LIMIT_WINDOW_SECONDS,
)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0
    count: int = 0
    limit: int = 0


_BUCKETS: dict[tuple[str, int, int], Deque[datetime]] = defaultdict(deque)
_BOUND = 5000
_EXPENSIVE_COMMANDS = {
    "monthfm",
    "weekfm",
    "songcharts",
    "radiofm",
    "tcanvas",
    "tly",
    "tstory",
    "tnow",
    "myself",
    "albnow",
    "nowp",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _limit_for(command: str) -> int:
    if command.lower().lstrip("/") in _EXPENSIVE_COMMANDS:
        return max(1, COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW)
    return max(1, COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW)


def check_command_rate_limit(command: str, user_id: int, chat_id: int) -> RateLimitResult:
    if not COMMAND_RATE_LIMIT_ENABLED:
        return RateLimitResult(True)
    now = utcnow()
    window = timedelta(seconds=max(1, COMMAND_RATE_LIMIT_WINDOW_SECONDS))
    command_key = command.lower().lstrip("/")
    limit = _limit_for(command_key)
    key = (command_key, int(user_id), int(chat_id))
    q = _BUCKETS[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        retry_after = max(1, int((window - (now - q[0])).total_seconds())) if q else max(1, COMMAND_RATE_LIMIT_WINDOW_SECONDS)
        return RateLimitResult(False, retry_after_seconds=retry_after, count=len(q), limit=limit)
    q.append(now)
    if len(_BUCKETS) > _BOUND:
        _BUCKETS.clear()
    return RateLimitResult(True, count=len(q), limit=limit)


def reset_rate_limits() -> None:
    _BUCKETS.clear()


def rate_limit_status() -> dict[str, object]:
    return {"enabled": COMMAND_RATE_LIMIT_ENABLED, "buckets": len(_BUCKETS)}


async def enforce_message_rate_limit(message, command: str) -> bool:
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    if not user or not chat:
        return True
    result = check_command_rate_limit(command, int(user.id), int(chat.id))
    if result.allowed:
        return True
    await message.answer(
        f"Aguarde {result.retry_after_seconds}s antes de usar /{command} novamente.",
        parse_mode="HTML",
    )
    return False
