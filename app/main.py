from __future__ import annotations

from pathlib import Path

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

from app.logging_safety import configure_safe_logging

configure_safe_logging()

from app.bot.monthfm import router as monthfm_router
from app.bot.owner_universal import router as owner_universal_router
from app.bot.owner_manual_register import router as owner_manual_register_router
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
from app.bot.music_inline import router as music_inline_router
from app.bot.music_extras import register_music_extra_handlers
from app.bot.music_groups import ensure_tables as ensure_music_group_tables, remember_group
from app.config.settings import BASE_URL, TELEGRAM_BOT_TOKEN, TIGRAO_FSM_ENABLED, telegram_webhook_secret, validate_required_env
from app.db.database import engine, init_db, run_migrations
from app.security.rate_limit import rate_limit_status
from app.services.telegram_user_profiles import telegram_user_profile_service
from app.web_music.router import router as web_music_router
from app.web_music.state import set_web_music_bot
from app.plugins.tigrao_fsm import build_tigrao_fsm_plugin

app = FastAPI(title="TR4 Music Only")
app.include_router(web_music_router)
logger = logging.getLogger(__name__)

bot: Bot | None = None
dispatcher: Dispatcher = bot_dispatcher
_telegram_dispatcher_configured = False
_telegram_startup_task: asyncio.Task | None = None
_telegram_startup_status = "pending"
_telegram_startup_error: str | None = None
tigrao_plugin = build_tigrao_fsm_plugin() if TIGRAO_FSM_ENABLED else None
_db_startup_status = "pending"
_db_startup_error: str | None = None


def _message_from_update(update: Update):
    return getattr(update, "message", None) or getattr(update, "edited_message", None)


def _tigrao_user_id_from_update(update: Update) -> int | None:
    for attr, user_attrs in (
        ("message", ("from_user",)),
        ("edited_message", ("from_user",)),
        ("callback_query", ("from_user",)),
        ("inline_query", ("from_user",)),
        ("chosen_inline_result", ("from_user",)),
        ("message_reaction", ("user",)),
        ("chat_member", ("from_user",)),
        ("my_chat_member", ("from_user",)),
        ("chat_join_request", ("from_user",)),
    ):
        obj = getattr(update, attr, None)
        if obj is None:
            continue
        for user_attr in user_attrs:
            user = getattr(obj, user_attr, None)
            if user is None:
                continue
            try:
                return int(getattr(user, "id"))
            except Exception:
                return None
    return None


def _telegram_allowed_updates() -> list[str]:
    base = set(dispatcher.resolve_used_update_types()) | {"chosen_inline_result"}
    if TIGRAO_FSM_ENABLED:
        base |= {
            "chat_join_request",
            "chat_member",
            "message_reaction",
            "message_reaction_count",
            "callback_query",
        }
    return sorted(base)


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


def _remember_telegram_users_from_update(update: Update) -> None:
    """Persist Telegram identity data from every update surface we receive."""
    candidates: list[tuple[object, str]] = []
    for attr, source in (
        ("message", "message"),
        ("edited_message", "edited_message"),
        ("channel_post", "channel_post"),
        ("edited_channel_post", "edited_channel_post"),
        ("callback_query", "callback_query"),
        ("inline_query", "inline_query"),
        ("chosen_inline_result", "chosen_inline_result"),
        ("shipping_query", "shipping_query"),
        ("pre_checkout_query", "pre_checkout_query"),
        ("poll_answer", "poll_answer"),
        ("message_reaction", "message_reaction"),
        ("chat_member", "chat_member"),
        ("my_chat_member", "my_chat_member"),
        ("chat_join_request", "chat_join_request"),
    ):
        obj = getattr(update, attr, None)
        if obj is None:
            continue
        for user_attr in ("from_user", "user"):
            user = getattr(obj, user_attr, None)
            if user is not None:
                candidates.append((user, source))
    seen: set[int] = set()
    for user, source in candidates:
        try:
            uid = int(getattr(user, "id", 0) or 0)
        except Exception:
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        telegram_user_profile_service.upsert_from_telegram_user(user, source=source)


async def _configure_telegram_bot_background() -> None:
    """Configure Telegram without blocking Railway /healthz startup.

    Railway health checks only need the HTTP server to answer /healthz.
    Network calls to Telegram (set_webhook/setup commands) can take longer than
    the first health-check attempt, so this task finishes Telegram setup after
    FastAPI has already started serving HTTP.
    """
    global bot, _telegram_dispatcher_configured, _telegram_startup_status, _telegram_startup_error
    _telegram_startup_status = "starting"
    _telegram_startup_error = None
    local_bot: Bot | None = None
    try:
        local_bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        if not _telegram_dispatcher_configured:
            dispatcher.include_router(monthfm_router)
            dispatcher.include_router(owner_universal_router)
            dispatcher.include_router(owner_manual_register_router)
            dispatcher.include_router(weekfm_router)
            dispatcher.include_router(tnow_router)
            dispatcher.include_router(tcanvas_router)
            dispatcher.include_router(tstory_router)
            dispatcher.include_router(tly_router)
            dispatcher.include_router(radiofm_router)
            dispatcher.include_router(myself_router)
            dispatcher.include_router(songcharts_router)
            dispatcher.include_router(music_inline_router)
            register_music_extra_handlers(dispatcher)
            if TIGRAO_FSM_ENABLED and tigrao_plugin is not None:
                tigrao_plugin.mount(dispatcher)
            _register_handlers(dispatcher)
            _telegram_dispatcher_configured = True
        webhook_secret = telegram_webhook_secret()
        await local_bot.set_webhook(
            f"{BASE_URL}/webhook",
            allowed_updates=_telegram_allowed_updates(),
            secret_token=webhook_secret,
        )
        await setup_bot_commands(local_bot)
        bot = local_bot
        set_web_music_bot(local_bot)
        _telegram_startup_status = "ready"
        logger.info("TELEGRAM_STARTUP_READY")
    except Exception as exc:
        _telegram_startup_status = "failed"
        _telegram_startup_error = f"{type(exc).__name__}: {exc}"
        logger.exception("TELEGRAM_STARTUP_FAILED")
        if local_bot:
            await local_bot.session.close()
        set_web_music_bot(None)
        bot = None


def _initialize_database_safely() -> None:
    global _db_startup_status, _db_startup_error
    _db_startup_status = "starting"
    _db_startup_error = None
    try:
        init_db()
        run_migrations(engine)
        ensure_music_group_tables()
        _db_startup_status = "ready"
        logger.info("DATABASE_STARTUP_READY")
    except Exception as exc:
        _db_startup_status = "failed"
        _db_startup_error = f"{type(exc).__name__}: {exc}"
        logger.exception("DATABASE_STARTUP_FAILED")


@app.on_event("startup")
async def on_startup() -> None:
    global _telegram_startup_task, _telegram_startup_status, _telegram_startup_error
    missing_env = validate_required_env()
    if missing_env:
        logger.warning("STARTUP_MISSING_ENV_VARS vars=%s", ",".join(missing_env))
    _initialize_database_safely()
    if not TELEGRAM_BOT_TOKEN:
        _telegram_startup_status = "skipped_missing_token"
        logger.warning("TELEGRAM_STARTUP_SKIPPED reason=missing_token")
        return

    _telegram_startup_task = asyncio.create_task(_configure_telegram_bot_background())


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
        set_web_music_bot(None)
        bot = None


def _db_ready_check() -> tuple[bool, str | None]:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except SQLAlchemyError as exc:
        return False, f"{type(exc).__name__}: {exc}"



_INLINE_ICON_DIR = Path(__file__).resolve().parent / "static" / "inline_icons"
_INLINE_ICON_FILES = {
    "playing": "playing.png",
    "tly": "tly.png",
    "tcanvas": "tcanvas.png",
    "week": "week.png",
    "month": "month.png",
    "mosaic": "mosaic.png",
}


@app.get("/inline-icons/{name}.png")
def inline_icon(name: str) -> Response:
    filename = _INLINE_ICON_FILES.get(name)
    if not filename:
        return Response(status_code=404)
    path = _INLINE_ICON_DIR / filename
    if not path.is_file():
        return Response(status_code=404)
    return Response(
        path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

@app.get("/healthz", status_code=200)
def healthz() -> dict[str, str]:
    """Liveness check para Railway.

    Não toca DB, Telegram, storage, filesystem ou rede.
    """
    return {"status": "ok"}



@app.get("/readyz")
def readyz() -> JSONResponse:
    db_ok, db_error = _db_ready_check()
    ok = bool(db_ok and TELEGRAM_BOT_TOKEN and bot is not None and _telegram_dispatcher_configured)
    return JSONResponse(
        {
            "status": "ready" if ok else "not_ready",
            "mode": "music_only",
            "checks": {
                "database": {"ok": db_ok, "error": db_error, "startup_status": _db_startup_status, "startup_error": _db_startup_error},
                "bot_token_configured": bool(TELEGRAM_BOT_TOKEN),
                "dispatcher_configured": _telegram_dispatcher_configured,
                "telegram_startup": {
                    "status": _telegram_startup_status,
                    "error": _telegram_startup_error,
                },
            },
        },
        status_code=200 if ok else 503,
    )


@app.post("/webhook")
async def telegram_webhook(request: Request) -> object:
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
        _remember_telegram_users_from_update(update)
        consumed = False
        if TIGRAO_FSM_ENABLED and tigrao_plugin is not None:
            try:
                tigrao_plugin.set_current_user(_tigrao_user_id_from_update(update))
                consumed = await tigrao_plugin.before_dispatch(bot, update)
            except Exception:
                logger.exception("TIGRAO_FSM_BEFORE_DISPATCH_ERROR")
                consumed = False
        if not consumed:
            await dispatcher.feed_update(bot, update)
    except Exception:
        logger.exception("WEBHOOK_ERROR_MUSIC_ONLY")
        return {"ok": True}
    return {"ok": True}
