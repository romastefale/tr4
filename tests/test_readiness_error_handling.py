from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.security.error_handling import normalize_exception


def test_normalize_generic_exception():
    normalized = normalize_exception(RuntimeError("falha"))
    assert normalized.category == "unexpected"
    assert normalized.retryable is False


def test_normalize_telegram_bad_request():
    exc = TelegramBadRequest(method="sendMessage", message="Bad Request: chat not found")
    normalized = normalize_exception(exc)
    assert normalized.category == "telegram_bad_request"
    assert normalized.retryable is False


def test_normalize_telegram_forbidden():
    exc = TelegramForbiddenError(method="sendMessage", message="Forbidden: bot was blocked by the user")
    normalized = normalize_exception(exc)
    assert normalized.category == "telegram_forbidden"
    assert normalized.retryable is False
