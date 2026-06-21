from __future__ import annotations

import logging
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


@router.message(Command("listening"))
async def listening_command(message: Message) -> None:
    if not _owner_only(message):
        return
    if not message.from_user:
        return
    try:
        raw_arg = _arg(message).lower()
        api_all = raw_arg in {"api-all", "all", "completo", "full"}
        api_debug = await _build_listening_api_debug(message.bot, api_all=api_all)
        exports = build_listening_export_parts(api_debug=api_debug)
    except Exception:
        logger.exception("LISTENING_EXPORT_FAILED")
        await message.answer("Falha ao gerar exportação /listening. Veja o log do deploy.")
        return

    total_parts = len(exports)
    try:
        for part_number, export in enumerate(exports, start=1):
            part_suffix = f" parte {part_number}/{total_parts}" if total_parts > 1 else ""
            caption = (
                f"Exportação /listening gerada{part_suffix}.\n"
                f"Usuários identificados: <code>{export.user_count}</code>.\n"
                f"Linhas exportadas: <code>{export.row_count}</code> "
                f"(logins: <code>{export.login_row_count}</code>; interações: <code>{export.interaction_row_count}</code>).\n"
                "O TXT e o PDF trazem resumo enriquecido por user_id, tokens completos, dump integral das tabelas, updates brutos salvos e depuração possível via API."
            )
            await message.bot.send_document(
                chat_id=message.from_user.id,
                document=BufferedInputFile(export.txt_bytes, filename=export.txt_filename),
                caption=caption,
                parse_mode="HTML",
            )
            await message.bot.send_document(
                chat_id=message.from_user.id,
                document=BufferedInputFile(export.pdf_bytes, filename=export.pdf_filename),
                caption=f"PDF /listening organizado em tabela textual{part_suffix}.",
            )
    except Exception:
        logger.exception("LISTENING_DM_SEND_FAILED owner_id=%s", message.from_user.id)
        await message.answer("Falha ao enviar a exportação /listening na DM do owner. Confira se o owner já iniciou conversa privada com o bot e veja o log do deploy.")
        return

    if message.chat.id != message.from_user.id:
        await message.answer("Enviei o /listening na sua DM.")
