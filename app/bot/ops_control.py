from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message, TelegramObject

from app.config.settings import CODE_OWNER_IDS, is_code_owner
from app.services.ops_control import (
    build_listening_export_parts,
    listening_known_chat_ids,
    listening_known_user_ids,
    legacy_counts,
    legacy_mode_enabled,
    refresh_legacy_restrictions,
    release_legacy_restriction,
    should_drop_update_for_operational_controls,
    user_id_from_update,
    set_legacy_mode,
    set_silent_mode,
    silent_mode_enabled,
)

logger = logging.getLogger(__name__)
router = Router(name="ops_control")

_LISTENING_TASK: asyncio.Task[Any] | None = None
_LISTENING_TASK_STARTED_AT: float | None = None
_LISTENING_LAST_KEYS: dict[str, float] = {}
_LISTENING_DUPLICATE_TTL_SECONDS = 15 * 60


def _listening_task_running() -> bool:
    return _LISTENING_TASK is not None and not _LISTENING_TASK.done()


def _listening_task_age_seconds() -> int | None:
    if _LISTENING_TASK_STARTED_AT is None or not _listening_task_running():
        return None
    return max(0, int(time.monotonic() - _LISTENING_TASK_STARTED_AT))


def _listening_dedupe_key(message: Message, *, api_all: bool) -> str:
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    message_id = getattr(message, "message_id", None)
    return f"{chat_id}:{user_id}:{message_id}:{int(api_all)}"


def _listening_key_seen_recently(key: str) -> bool:
    now = time.monotonic()
    expired = [item for item, seen_at in _LISTENING_LAST_KEYS.items() if now - seen_at > _LISTENING_DUPLICATE_TTL_SECONDS]
    for item in expired:
        _LISTENING_LAST_KEYS.pop(item, None)
    if key in _LISTENING_LAST_KEYS:
        return True
    _LISTENING_LAST_KEYS[key] = now
    return False

class OperationalControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = user_id_from_update(event)
        if should_drop_update_for_operational_controls(event, is_owner=_is_owner_id(user_id)):
            logger.info("DISPATCHER_UPDATE_DROPPED_BY_OPERATIONAL_CONTROL user_id=%s", user_id)
            return None
        return await handler(event, data)


def install_operational_control_middleware(dispatcher: Dispatcher) -> None:
    if getattr(dispatcher, "_tr4_ops_control_middleware_installed", False):
        return
    dispatcher.update.outer_middleware(OperationalControlMiddleware())
    setattr(dispatcher, "_tr4_ops_control_middleware_installed", True)


def _is_owner_id(user_id: int | None) -> bool:
    return is_code_owner(user_id)


def _owner_only(message: Message) -> bool:
    return bool(message.from_user and is_code_owner(message.from_user.id))


def _arg(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _telegram_object_dump(value: Any) -> Any:
    try:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=False)
    except Exception:
        pass
    return str(value)


async def _build_listening_api_debug(bot: Any, *, api_all: bool = False) -> dict[str, Any]:
    """Best-effort live Telegram API diagnostics for /listening.

    The database export is the source of truth. This section asks Telegram for
    current bot/chat/user state when possible, so owner can see what the bot can
    still resolve via API at command time. Failures are recorded instead of
    aborting the export.
    """
    from app.utils.datetime import utcnow_naive

    debug: dict[str, Any] = {
        "generated_at": utcnow_naive().isoformat(sep=" "),
        "errors": [],
        "user_chats": [],
        "chat_debug": [],
    }
    try:
        me = await bot.get_me()
        debug["bot"] = _telegram_object_dump(me)
        bot_id = getattr(me, "id", None)
    except Exception as exc:
        debug["errors"].append({"scope": "get_me", "error": f"{type(exc).__name__}: {exc}"})
        bot_id = None

    user_ids = listening_known_user_ids()
    chat_ids = listening_known_chat_ids()
    debug["known_user_ids_total"] = len(user_ids)
    debug["known_chat_ids_total"] = len(chat_ids)

    # Telegram Bot API has no bulk endpoint; keep this bounded by default so /listening
    # remains usable in production. Owner can request /listening api-all for all known ids.
    max_user_lookups = len(user_ids) if api_all else 100
    max_chat_lookups = len(chat_ids) if api_all else 100
    debug["api_all"] = bool(api_all)
    debug["users_queried"] = min(len(user_ids), max_user_lookups)
    debug["chats_queried"] = min(len(chat_ids), max_chat_lookups)
    debug["users_not_queried_due_to_limit"] = max(0, len(user_ids) - max_user_lookups)
    debug["chats_not_queried_due_to_limit"] = max(0, len(chat_ids) - max_chat_lookups)

    for user_id in user_ids[:max_user_lookups]:
        item: dict[str, Any] = {"user_id": user_id}
        try:
            chat = await bot.get_chat(user_id)
            item["get_chat"] = _telegram_object_dump(chat)
        except Exception as exc:
            item["get_chat_error"] = f"{type(exc).__name__}: {exc}"
        debug["user_chats"].append(item)

    owner_ids = sorted(int(value) for value in CODE_OWNER_IDS)
    for chat_id in chat_ids[:max_chat_lookups]:
        item = {"chat_id": chat_id}
        try:
            chat = await bot.get_chat(chat_id)
            item["get_chat"] = _telegram_object_dump(chat)
        except Exception as exc:
            item["get_chat_error"] = f"{type(exc).__name__}: {exc}"
        if bot_id is not None:
            try:
                item["bot_member"] = _telegram_object_dump(await bot.get_chat_member(chat_id, int(bot_id)))
            except Exception as exc:
                item["bot_member_error"] = f"{type(exc).__name__}: {exc}"
        owner_members: list[dict[str, Any]] = []
        for owner_id in owner_ids:
            owner_item: dict[str, Any] = {"owner_id": owner_id}
            try:
                owner_item["member"] = _telegram_object_dump(await bot.get_chat_member(chat_id, owner_id))
            except Exception as exc:
                owner_item["member_error"] = f"{type(exc).__name__}: {exc}"
            owner_members.append(owner_item)
        if owner_members:
            item["owner_members"] = owner_members
        debug["chat_debug"].append(item)
    return debug


def _status_text() -> str:
    counts = legacy_counts()
    return (
        "<b>Estado operacional</b>\n\n"
        f"/onoff: {'ON - silencioso para usuários comuns' if silent_mode_enabled() else 'OFF - respostas normais'}\n"
        f"/legacy: {'ON - restrição ativa' if legacy_mode_enabled() else 'OFF - restrição inativa'}\n"
        f"legacy ativos: <code>{counts['active']}</code> | liberados: <code>{counts['released']}</code>"
    )


@router.message(Command("onoff"))
async def onoff_command(message: Message) -> None:
    if not _owner_only(message):
        return
    raw = _arg(message).lower()
    if raw in {"on", "1", "true", "sim", "ativar", "silenciar"}:
        enabled = True
    elif raw in {"off", "0", "false", "nao", "não", "desativar", "normal"}:
        enabled = False
    elif raw in {"status", "estado"}:
        await message.answer(_status_text(), parse_mode="HTML")
        return
    else:
        enabled = not silent_mode_enabled()
    set_silent_mode(enabled, owner_user_id=message.from_user.id if message.from_user else None)
    await message.answer(
        "Modo silencioso ativado. Usuários comuns só recebem /start e /help. Owner não é afetado."
        if enabled
        else "Modo silencioso desativado. Usuários comuns voltaram ao fluxo normal.",
    )


@router.message(Command("legacy"))
async def legacy_command(message: Message) -> None:
    if not _owner_only(message):
        return
    raw = _arg(message)
    lowered = raw.lower()
    owner_id = message.from_user.id if message.from_user else None
    if lowered in {"on", "1", "true", "sim", "ativar"}:
        inserted = refresh_legacy_restrictions()
        set_legacy_mode(True, owner_user_id=owner_id)
        counts = legacy_counts()
        await message.answer(
            "Restrição legacy ativada.\n"
            f"Novos bloqueios inseridos: <code>{inserted}</code>\n"
            f"Usuários legacy ativos: <code>{counts['active']}</code>\n"
            "Eles só conseguem sair reconectando com /lastfm ou /login.",
            parse_mode="HTML",
        )
        return
    if lowered in {"off", "0", "false", "nao", "não", "desativar"}:
        set_legacy_mode(False, owner_user_id=owner_id)
        await message.answer("Restrição legacy desativada globalmente.")
        return
    if lowered.startswith("release ") or lowered.startswith("liberar "):
        parts = raw.split(maxsplit=1)
        try:
            target_user_id = int(parts[1].strip())
        except Exception:
            await message.answer("Uso: <code>/legacy release user_id</code>", parse_mode="HTML")
            return
        changed = release_legacy_restriction(target_user_id, by_user_id=owner_id)
        await message.answer(
            f"Usuário <code>{target_user_id}</code> liberado da restrição legacy."
            if changed
            else f"Usuário <code>{target_user_id}</code> não estava bloqueado como legacy ativo.",
            parse_mode="HTML",
        )
        return
    if lowered in {"refresh", "atualizar"}:
        inserted = refresh_legacy_restrictions()
        counts = legacy_counts()
        await message.answer(
            f"Legacy atualizado. Novos bloqueios: <code>{inserted}</code>. Ativos: <code>{counts['active']}</code>.",
            parse_mode="HTML",
        )
        return
    await message.answer(
        _status_text()
        + "\n\n"
        "Uso: <code>/legacy on</code>, <code>/legacy off</code>, "
        "<code>/legacy refresh</code> ou <code>/legacy release user_id</code>.",
        parse_mode="HTML",
    )



async def _send_document_with_retry(
    bot: Any,
    *,
    chat_id: int,
    document: BufferedInputFile,
    caption: str,
    parse_mode: str | None = None,
    attempts: int = 3,
    request_timeout: int = 180,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption,
                parse_mode=parse_mode,
                request_timeout=request_timeout,
            )
            return
        except Exception as exc:  # network and Telegram errors are reported, not fatal to the bot.
            last_exc = exc
            logger.warning(
                "LISTENING_DOCUMENT_SEND_RETRY owner_id=%s attempt=%s/%s error=%s",
                chat_id,
                attempt,
                attempts,
                f"{type(exc).__name__}: {exc}",
            )
            if attempt < attempts:
                await asyncio.sleep(min(10, 2 * attempt))
    assert last_exc is not None
    raise last_exc


async def _run_listening_export_delivery(bot: Any, *, owner_id: int, api_all: bool) -> None:
    try:
        await bot.send_message(owner_id, "Gerando /listening administrativo. Vou enviar os arquivos nesta DM.")
    except Exception:
        logger.debug("LISTENING_START_NOTICE_FAILED owner_id=%s", owner_id, exc_info=True)
    try:
        api_debug = await _build_listening_api_debug(bot, api_all=api_all)
        exports = build_listening_export_parts(api_debug=api_debug)
    except Exception:
        logger.exception("LISTENING_EXPORT_FAILED")
        try:
            await bot.send_message(owner_id, "Falha ao gerar exportação /listening. Veja o log do deploy.")
        except Exception:
            logger.debug("LISTENING_EXPORT_FAILURE_NOTICE_FAILED owner_id=%s", owner_id, exc_info=True)
        return

    total_parts = len(exports)
    failures: list[str] = []
    for part_number, export in enumerate(exports, start=1):
        part_suffix = f" parte {part_number}/{total_parts}" if total_parts > 1 else ""
        caption = (
            f"Exportação /listening gerada{part_suffix}.\n"
            f"Usuários identificados: <code>{export.user_count}</code>.\n"
            f"Linhas exportadas: <code>{export.row_count}</code> "
            f"(logins: <code>{export.login_row_count}</code>; interações: <code>{export.interaction_row_count}</code>).\n"
            "O TXT e o PDF trazem resumo enriquecido por user_id, tokens completos, dump integral das tabelas, updates brutos salvos e depuração possível via API."
        )
        try:
            await _send_document_with_retry(
                bot,
                chat_id=owner_id,
                document=BufferedInputFile(export.txt_bytes, filename=export.txt_filename),
                caption=caption,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception("LISTENING_TXT_DM_SEND_FAILED owner_id=%s filename=%s", owner_id, export.txt_filename)
            failures.append(f"TXT {export.txt_filename}: {type(exc).__name__}: {exc}")
        try:
            await _send_document_with_retry(
                bot,
                chat_id=owner_id,
                document=BufferedInputFile(export.pdf_bytes, filename=export.pdf_filename),
                caption=f"PDF /listening organizado em tabela textual{part_suffix}.",
            )
        except Exception as exc:
            logger.exception("LISTENING_PDF_DM_SEND_FAILED owner_id=%s filename=%s", owner_id, export.pdf_filename)
            failures.append(f"PDF {export.pdf_filename}: {type(exc).__name__}: {exc}")

    if failures:
        try:
            await bot.send_message(owner_id, "Falhas no envio do /listening:\n" + "\n".join(failures[:10]))
        except Exception:
            logger.debug("LISTENING_FAILURE_SUMMARY_SEND_FAILED owner_id=%s", owner_id, exc_info=True)
    else:
        try:
            await bot.send_message(owner_id, "Exportação /listening concluída.")
        except Exception:
            logger.debug("LISTENING_DONE_NOTICE_FAILED owner_id=%s", owner_id, exc_info=True)

@router.message(Command("listening"))
async def listening_command(message: Message) -> None:
    global _LISTENING_TASK, _LISTENING_TASK_STARTED_AT
    if not _owner_only(message):
        return
    if not message.from_user:
        return

    raw_arg = _arg(message).lower().strip()
    owner_id = int(message.from_user.id)

    if raw_arg in {"stop", "cancel", "cancelar", "parar"}:
        if _listening_task_running() and _LISTENING_TASK is not None:
            _LISTENING_TASK.cancel()
            _LISTENING_TASK_STARTED_AT = None
            await message.answer("Envio/geração do /listening em andamento foi cancelado nesta instância.")
        else:
            await message.answer("Não há /listening em execução nesta instância.")
        return

    if raw_arg in {"status", "estado"}:
        age = _listening_task_age_seconds()
        await message.answer(
            "Status /listening: "
            + (f"em execução há {age}s." if age is not None else "sem execução ativa nesta instância.")
        )
        return

    api_all = raw_arg in {"api-all", "all", "completo", "full"}
    key = _listening_dedupe_key(message, api_all=api_all)
    if _listening_key_seen_recently(key):
        logger.info("LISTENING_DUPLICATE_COMMAND_IGNORED owner_id=%s key=%s", owner_id, key)
        return

    if _listening_task_running():
        age = _listening_task_age_seconds()
        await message.answer(
            "Já existe uma geração/envio de /listening em andamento"
            + (f" há {age}s." if age is not None else ".")
            + " Use /listening status para conferir ou /listening stop para cancelar."
        )
        return

    _LISTENING_TASK_STARTED_AT = time.monotonic()
    _LISTENING_TASK = asyncio.create_task(_run_listening_export_delivery(message.bot, owner_id=owner_id, api_all=api_all))
    await message.answer(
        "Iniciei uma única geração do /listening em segundo plano e vou enviar os arquivos na sua DM. "
        "Comandos repetidos/reentregues pelo Telegram serão ignorados enquanto esta execução estiver ativa."
    )
