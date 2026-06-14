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
from app.bot.music_broadcast import router as music_broadcast_router
from app.bot.myself import router as myself_router
from app.bot.radiofm import router as radiofm_router
from app.bot.setup_commands import setup_bot_commands
from app.bot.show_owner import router as show_owner_router
from app.bot.tgov_owner import router as tgov_owner_router
from app.fsm_tigrao.router import router as fsm_tigrao_router
from app.bot.songcharts import router as songcharts_router
from app.bot.tcanvas import router as tcanvas_router
from app.bot.telegram import _register_handlers, bot_dispatcher, shutdown_telegram_bot
from app.bot.tly import router as tly_router
from app.bot.tnow import router as tnow_router
from app.bot.tstory import router as tstory_router
from app.bot.weekfm import router as weekfm_router
from app.bot.music_extras import register_music_extra_handlers
from app.bot.music_groups import ensure_tables as ensure_music_group_tables, remember_group
from app.bot.music_broadcast import run_due_music_broadcast_schedules
from app.bot.owner_daily_summary import send_daily_limit_summary_to_owners
from app.config import settings
from app.config.settings import (
    BASE_URL,
    TELEGRAM_BOT_TOKEN,
    TR4_EQUALIZADOR_ENABLED,
    TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
    TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE,
    TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
    RADIO_SCHEDULER_ENABLED,
    telegram_webhook_secret,
    validate_required_env,
)
from app.db.database import engine, init_db, run_migrations
from app.security.rate_limit import rate_limit_status
from app.equalizador.hardening import equalizador_hardening_status
from app.equalizador.ddx import equalizador_ddx_preprocess_update, process_due_ddx_soft_deletions
from app.equalizador.reacoes import record_reaction_update_payload
from app.equalizador.novos_membros import equalizador_novos_membros_preprocess_update
from app.equalizador.persistencia import ensure_persistence_state
from app.fsm_tigrao.x9 import record_x9_update_context

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
_radio_scheduler_task: asyncio.Task | None = None
_ddx_scheduler_task: asyncio.Task | None = None
_music_broadcast_scheduler_task: asyncio.Task | None = None


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
    dispatcher.include_router(music_broadcast_router)
    dispatcher.include_router(radiofm_router)
    dispatcher.include_router(myself_router)
    dispatcher.include_router(songcharts_router)
    dispatcher.include_router(show_owner_router)
    dispatcher.include_router(tgov_owner_router)
    dispatcher.include_router(fsm_tigrao_router)
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
            allowed_updates=sorted(set(dispatcher.resolve_used_update_types()) | {"message_reaction", "message_reaction_count"}),
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


async def _radio_scheduler_loop() -> None:
    """Best-effort Equalizador Radio scheduler.

    Runs due scheduled text publications without blocking Telegram startup. It is
    intentionally quiet on missing token/config so Railway can still boot.
    """
    if not TR4_EQUALIZADOR_ENABLED or not TELEGRAM_BOT_TOKEN:
        return
    from app.equalizador.radio import run_due_radio_schedules

    while True:
        try:
            await run_due_radio_schedules(
                bot_token=TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                limit=10,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("EQUALIZADOR_RADIO_SCHEDULER_TICK_FAILED", exc_info=True)
        await asyncio.sleep(60)


async def _ddx_scheduler_loop() -> None:
    """Durable Equalizador DDX soft-delete scheduler.

    In-memory tasks handle the normal 10-minute delay while the process stays
    alive. This loop processes overdue rows from eq_ddx_soft_pending after a
    deploy/restart so scheduled DDX deletions are not lost.
    """
    if not TR4_EQUALIZADOR_ENABLED or not TELEGRAM_BOT_TOKEN:
        return
    while True:
        try:
            if bot is not None:
                await process_due_ddx_soft_deletions(bot, limit=20)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("EQUALIZADOR_DDX_SCHEDULER_TICK_FAILED", exc_info=True)
        await asyncio.sleep(10)


async def _music_broadcast_scheduler_loop() -> None:
    """Owner-configured music broadcast scheduler.

    Processes durable broadcast schedules every minute. Each schedule stores its
    own last processed slot so restarts do not send duplicate hourly cards.
    """
    if not TR4_EQUALIZADOR_ENABLED or not TELEGRAM_BOT_TOKEN:
        return
    while True:
        try:
            if bot is not None:
                await run_due_music_broadcast_schedules(bot, limit=10)
                await send_daily_limit_summary_to_owners(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("MUSIC_BROADCAST_SCHEDULER_TICK_FAILED", exc_info=True)
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_startup() -> None:
    global bot, _telegram_startup_task, _telegram_ready, _telegram_startup_error, _radio_scheduler_task, _ddx_scheduler_task, _music_broadcast_scheduler_task
    missing_env = validate_required_env()
    if missing_env:
        logger.warning("STARTUP_MISSING_ENV_VARS vars=%s", ",".join(missing_env))
    init_db()
    run_migrations(engine)
    try:
        ensure_persistence_state(engine)
    except Exception:
        logger.warning("TR4_PERSISTENCE_GUARD_STARTUP_FAILED", exc_info=True)
    ensure_music_group_tables()
    _telegram_ready = False
    _telegram_startup_error = None
    if TR4_EQUALIZADOR_ENABLED and RADIO_SCHEDULER_ENABLED and TELEGRAM_BOT_TOKEN and _radio_scheduler_task is None:
        _radio_scheduler_task = asyncio.create_task(_radio_scheduler_loop())
        logger.info("EQUALIZADOR_RADIO_SCHEDULER_SCHEDULED")
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_STARTUP_SKIPPED reason=missing_token")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        if TR4_EQUALIZADOR_ENABLED and _ddx_scheduler_task is None:
            _ddx_scheduler_task = asyncio.create_task(_ddx_scheduler_loop())
            logger.info("EQUALIZADOR_DDX_SCHEDULER_SCHEDULED")
        if TR4_EQUALIZADOR_ENABLED and _music_broadcast_scheduler_task is None:
            _music_broadcast_scheduler_task = asyncio.create_task(_music_broadcast_scheduler_loop())
            logger.info("MUSIC_BROADCAST_SCHEDULER_SCHEDULED")
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
    global bot, _telegram_startup_task, _radio_scheduler_task, _ddx_scheduler_task, _music_broadcast_scheduler_task
    if _telegram_startup_task and not _telegram_startup_task.done():
        _telegram_startup_task.cancel()
        try:
            await _telegram_startup_task
        except asyncio.CancelledError:
            pass
    if _radio_scheduler_task and not _radio_scheduler_task.done():
        _radio_scheduler_task.cancel()
        try:
            await _radio_scheduler_task
        except asyncio.CancelledError:
            pass
    _radio_scheduler_task = None
    if _ddx_scheduler_task and not _ddx_scheduler_task.done():
        _ddx_scheduler_task.cancel()
        try:
            await _ddx_scheduler_task
        except asyncio.CancelledError:
            pass
    _ddx_scheduler_task = None
    if _music_broadcast_scheduler_task and not _music_broadcast_scheduler_task.done():
        _music_broadcast_scheduler_task.cancel()
        try:
            await _music_broadcast_scheduler_task
        except asyncio.CancelledError:
            pass
    _music_broadcast_scheduler_task = None
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


@app.get("/favicon.ico", include_in_schema=False)
def root_favicon() -> Response:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='#161b20'/><path d='M18 35h28M22 25h20M26 45h12' stroke='#66aaff' stroke-width='5' stroke-linecap='round'/></svg>"""
    return Response(content=svg, media_type="image/svg+xml")


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
        record_reaction_update_payload(payload, alias_secret=settings.equalizador_alias_secret())
        update = Update.model_validate(payload, context={"bot": bot})
        _remember_music_group_from_update(update)
        # Fase 12D: X9 de contexto apenas alimenta o FSM privado.
        # O X9/DDX automático continua independente logo abaixo e pode agir
        # como antes, apagando/registrando/avisando quando houver regra ativa.
        record_x9_update_context(update)
        await equalizador_novos_membros_preprocess_update(bot, update, alias_secret=settings.equalizador_alias_secret())
        if await equalizador_ddx_preprocess_update(bot, update, alias_secret=settings.equalizador_alias_secret()):
            return {"ok": True}
        await dispatcher.feed_update(bot, update)
    except Exception:
        logger.exception("WEBHOOK_ERROR_MUSIC_ONLY")
        return {"ok": True}
    return {"ok": True}
