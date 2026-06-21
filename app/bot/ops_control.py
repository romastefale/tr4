from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message, TelegramObject

from app.config.settings import is_code_owner
from app.services.ops_control import (
    build_listening_export_parts,
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
        exports = build_listening_export_parts()
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
                f"Registros de login: <code>{export.row_count}</code>.\n"
                "O TXT contém os valores completos das tabelas de login; o PDF organiza os mesmos dados em páginas de tabela textual."
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
