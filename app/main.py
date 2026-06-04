from __future__ import annotations

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
from app.config.settings import BASE_URL, TELEGRAM_BOT_TOKEN, telegram_webhook_secret, validate_required_env
from app.db.database import engine, init_db, run_migrations
from app.security.rate_limit import rate_limit_status

app = FastAPI(title="TR4 Music Only")
logger = logging.getLogger(__name__)

bot: Bot | None = None
dispatcher: Dispatcher = bot_dispatcher
_telegram_dispatcher_configured = False


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


@app.on_event("startup")
async def on_startup() -> None:
    global bot, _telegram_dispatcher_configured
    missing_env = validate_required_env()
    if missing_env:
        logger.warning("STARTUP_MISSING_ENV_VARS vars=%s", ",".join(missing_env))
    init_db()
    run_migrations(engine)
    ensure_music_group_tables()
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_STARTUP_SKIPPED reason=missing_token")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        if not _telegram_dispatcher_configured:
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
        webhook_secret = telegram_webhook_secret()
        await bot.set_webhook(
            f"{BASE_URL}/webhook",
            allowed_updates=dispatcher.resolve_used_update_types(),
            secret_token=webhook_secret,
        )
        await setup_bot_commands(bot)
    except Exception:
        logger.exception("TELEGRAM_STARTUP_FAILED")
        if bot:
            await bot.session.close()
        bot = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global bot
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
    return {"status": "ok", "mode": "music_only", "rate_limit": rate_limit_status()}


@app.get("/readyz")
def readyz() -> JSONResponse:
    db_ok, db_error = _db_ready_check()
    ok = bool(db_ok and TELEGRAM_BOT_TOKEN and bot is not None and _telegram_dispatcher_configured)
    return JSONResponse(
        {
            "status": "ready" if ok else "not_ready",
            "mode": "music_only",
            "checks": {
                "database": {"ok": db_ok, "error": db_error},
                "bot_token_configured": bool(TELEGRAM_BOT_TOKEN),
                "dispatcher_configured": _telegram_dispatcher_configured,
            },
        },
        status_code=200 if ok else 503,
    )


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool] | Response:
    if bot is None:
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
