from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.bot.monthfm import router as monthfm_router
from app.bot.myself import router as myself_router
from app.bot.radiofm import router as radiofm_router
from app.bot.setup_commands import setup_bot_commands
from app.bot.songcharts import router as songcharts_router
from app.bot.tcanvas import router as tcanvas_router
from app.bot.telegram import _register_handlers, bot_dispatcher, shutdown_telegram_bot
from app.bot.tly import router as tly_router
from app.bot.tnow import router as tnow_router
from app.bot.tstory import router as tstory_router
from app.bot.weekfm import router as weekfm_router
from app.bot.music_extras import register_music_extra_handlers
from app.bot.music_groups import ensure_tables as ensure_music_group_tables, remember_group
from app.config import settings
from app.config.settings import (
    BASE_URL,
    TELEGRAM_BOT_TOKEN,
    TR4_EQUALIZADOR_ENABLED,
    TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
    TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE,
    TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
    telegram_webhook_secret,
    validate_required_env,
)
from app.db.database import engine, init_db, run_migrations
from app.security.rate_limit import rate_limit_status
from app.equalizador.hardening import equalizador_hardening_status

app = FastAPI(title="TR4 Music Only")
if TR4_EQUALIZADOR_ENABLED:
    from app.equalizador.router import router as equalizador_router

    app.include_router(equalizador_router)
logger = logging.getLogger(__name__)

bot: Bot | None = None
dispatcher: Dispatcher = bot_dispatcher
_telegram_dispatcher_configured = False
_telegram_ready = False
_telegram_startup_task: asyncio.Task | None = None
_telegram_startup_error: str | None = None


def _message_from_update(update: Update):
    return getattr(update, "message", None) or getattr(update, "edited_message", None)


def _remember_music_group_from_update(update: Update) -> None:
    message = _message_from_update(update)
    if not message or not getattr(message, "chat", None):
        return
    chat = message.chat
    if chat.type not in {"group", "supergroup"}:
        return
    try:
        remember_group(chat_id=int(chat.id), title=getattr(chat, "title", None), username=getattr(chat, "username", None))
        logger.info("MUSIC_GROUP_REMEMBERED | chat_id=%s | title=%s", chat.id, getattr(chat, "title", None))
    except Exception:
        logger.debug("MUSIC_GROUP_REMEMBER_FAILED", exc_info=True)


def _configure_dispatcher_once() -> None:
    global _telegram_dispatcher_configured
    if _telegram_dispatcher_configured:
        return
    dispatcher.include_router(monthfm_router)
    dispatcher.include_router(weekfm_router)
    dispatcher.include_router(tnow_router)
    dispatcher.include_router(tcanvas_router)
    dispatcher.include_router(tstory_router)
    dispatcher.include_router(tly_router)
    dispatcher.include_router(radiofm_router)
    dispatcher.include_router(myself_router)
    dispatcher.include_router(songcharts_router)
    register_music_extra_handlers(dispatcher)
    _register_handlers(dispatcher)
    _telegram_dispatcher_configured = True


async def _finish_telegram_startup() -> None:
    global bot, _telegram_ready, _telegram_startup_error
    try:
        if bot is None:
            _telegram_startup_error = "bot_not_initialized"
            return
        webhook_secret = telegram_webhook_secret()
        await bot.set_webhook(
            f"{BASE_URL}/webhook",
            allowed_updates=dispatcher.resolve_used_update_types(),
            secret_token=webhook_secret,
        )
        await setup_bot_commands(bot)
        _telegram_ready = True
        _telegram_startup_error = None
        logger.info("TELEGRAM_STARTUP_READY")
    except Exception as exc:
        _telegram_ready = False
        _telegram_startup_error = f"{type(exc).__name__}: {exc}"
        logger.exception("TELEGRAM_STARTUP_FAILED")
        if bot:
            await bot.session.close()
        bot = None


@app.on_event("startup")
async def on_startup() -> None:
    global bot, _telegram_startup_task, _telegram_ready, _telegram_startup_error
    missing_env = validate_required_env()
    if missing_env:
        logger.warning("STARTUP_MISSING_ENV_VARS vars=%s", ",".join(missing_env))
    init_db()
    run_migrations(engine)
    ensure_music_group_tables()
    _telegram_ready = False
    _telegram_startup_error = None
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_STARTUP_SKIPPED reason=missing_token")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        _configure_dispatcher_once()
        _telegram_startup_task = asyncio.create_task(_finish_telegram_startup())
        logger.info("TELEGRAM_STARTUP_SCHEDULED")
    except Exception as exc:
        _telegram_startup_error = f"{type(exc).__name__}: {exc}"
        logger.exception("TELEGRAM_STARTUP_SCHEDULE_FAILED")
        if bot:
            await bot.session.close()
        bot = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global bot, _telegram_startup_task
    if _telegram_startup_task and not _telegram_startup_task.done():
        _telegram_startup_task.cancel()
        try:
            await _telegram_startup_task
        except asyncio.CancelledError:
            pass
    await shutdown_telegram_bot()
    if bot:
        await bot.session.close()
        bot = None


def _db_ready_check() -> tuple[bool, str | None]:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except SQLAlchemyError as exc:
        return False, f"{type(exc).__name__}: {exc}"


@app.get("/healthz", status_code=200)
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": "music_only",
        "rate_limit": rate_limit_status(),
        "equalizador_enabled": TR4_EQUALIZADOR_ENABLED,
    }


@app.get("/readyz")
def readyz() -> JSONResponse:
    db_ok, db_error = _db_ready_check()
    ok = bool(db_ok and TELEGRAM_BOT_TOKEN and bot is not None and _telegram_dispatcher_configured and _telegram_ready)
    return JSONResponse(
        {
            "status": "ready" if ok else "not_ready",
            "mode": "music_only",
            "checks": {
                "database": {"ok": db_ok, "error": db_error},
                "bot_token_configured": bool(TELEGRAM_BOT_TOKEN),
                "dispatcher_configured": _telegram_dispatcher_configured,
                "telegram_ready": _telegram_ready,
                "telegram_startup_error": _telegram_startup_error,
                "equalizador": {
                    **equalizador_hardening_status(
                        enabled=TR4_EQUALIZADOR_ENABLED,
                        rate_limit_per_minute=TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE,
                        session_ttl_seconds=TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
                        initdata_max_age_seconds=TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
                    ),
                    "config_ok": settings.equalizador_config_ok(),
                    "config_errors": list(settings.equalizador_config_errors()),
                },
            },
        },
        status_code=200 if ok else 503,
    )


@app.post("/webhook", response_model=None)
async def telegram_webhook(request: Request):
    if bot is None or not _telegram_ready:
        return {"ok": True}
    expected_secret = telegram_webhook_secret()
    if expected_secret:
        provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided_secret, expected_secret):
            return Response(status_code=403)
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
        _remember_music_group_from_update(update)
        await dispatcher.feed_update(bot, update)
    except Exception:
        logger.exception("WEBHOOK_ERROR_MUSIC_ONLY")
        return {"ok": True}
    return {"ok": True}
