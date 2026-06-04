from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

try:
    from aiogram.exceptions import (
        TelegramAPIError,
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramRetryAfter,
        TelegramServerError,
    )
except Exception:  # pragma: no cover - keeps module importable in stripped environments
    TelegramAPIError = Exception
    TelegramBadRequest = Exception
    TelegramForbiddenError = Exception
    TelegramNetworkError = Exception
    TelegramRetryAfter = Exception
    TelegramServerError = Exception


@dataclass(frozen=True)
class NormalizedError:
    type: str
    category: str
    retryable: bool
    user_visible: str
    detail: str


def normalize_exception(exc: BaseException) -> NormalizedError:
    """Classify operational exceptions without exposing internals to users.

    This is intentionally conservative: it does not decide business logic, it
    only normalizes error metadata for logs/audit/readiness.
    """
    name = type(exc).__name__
    detail = str(exc)

    if isinstance(exc, TelegramRetryAfter):
        return NormalizedError(
            type=name,
            category="telegram_rate_limit",
            retryable=True,
            user_visible="Telegram pediu para aguardar antes de repetir.",
            detail=detail,
        )
    if isinstance(exc, TelegramNetworkError):
        return NormalizedError(
            type=name,
            category="telegram_network",
            retryable=True,
            user_visible="Falha temporária de rede com Telegram.",
            detail=detail,
        )
    if isinstance(exc, TelegramServerError):
        return NormalizedError(
            type=name,
            category="telegram_server",
            retryable=True,
            user_visible="Falha temporária do servidor Telegram.",
            detail=detail,
        )
    if isinstance(exc, TelegramForbiddenError):
        return NormalizedError(
            type=name,
            category="telegram_forbidden",
            retryable=False,
            user_visible="Telegram recusou a ação por permissão insuficiente ou bot bloqueado.",
            detail=detail,
        )
    if isinstance(exc, TelegramBadRequest):
        return NormalizedError(
            type=name,
            category="telegram_bad_request",
            retryable=False,
            user_visible="Telegram recusou a ação por dados inválidos ou estado inconsistente.",
            detail=detail,
        )
    if isinstance(exc, TelegramAPIError):
        return NormalizedError(
            type=name,
            category="telegram_api",
            retryable=False,
            user_visible="Telegram recusou a operação.",
            detail=detail,
        )
    return NormalizedError(
        type=name,
        category="unexpected",
        retryable=False,
        user_visible="Falha inesperada.",
        detail=detail,
    )


def error_payload(exc: BaseException) -> dict[str, Any]:
    return asdict(normalize_exception(exc))
