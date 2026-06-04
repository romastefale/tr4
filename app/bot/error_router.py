from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

from app.security.audit import log_audit_event
from app.security.error_handling import normalize_exception

router = Router(name="global_error_router")
logger = logging.getLogger(__name__)


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Last-resort aiogram error handler.

    It prevents unclassified dispatcher errors from bypassing structured logs.
    Returning True marks the error as handled by aiogram.
    """
    normalized = normalize_exception(event.exception)
    if normalized.retryable:
        logger.warning(
            "AIOGRAM_ERROR_HANDLED | category=%s | type=%s | detail=%s",
            normalized.category,
            normalized.type,
            normalized.detail,
        )
    else:
        logger.exception(
            "AIOGRAM_ERROR_HANDLED | category=%s | type=%s",
            normalized.category,
            normalized.type,
            exc_info=event.exception,
        )
    try:
        log_audit_event(
            category="runtime",
            action="aiogram_error",
            status="error",
            reason=normalized.category,
            payload={
                "type": normalized.type,
                "retryable": normalized.retryable,
                "detail": normalized.detail[:1000],
            },
        )
    except Exception:
        logger.debug("AIOGRAM_ERROR_AUDIT_FAILED", exc_info=True)
    return True
