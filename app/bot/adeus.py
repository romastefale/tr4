from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.filters import Command

from app.moderation_tigrao.display import group_display_name
from app.moderation_tigrao.permissions import is_owner_user
from app.security.adeus_recovery import (
    cancel_operation,
    confirm_operation,
    create_recovery_operation,
    execute_leave_operation,
    get_operation,
    list_recovery_items,
    list_recovery_operations,
    prepare_recovery_links,
)
from app.security.managed_groups import list_managed_groups

logger = logging.getLogger(__name__)

router = Router(name="adeus")


def _button(text: str, callback_data: str, style: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    kwargs: dict = {"text": text}
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = callback_data
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def _owner_only(callback: CallbackQuery) -> bool:
    return bool(callback.from_user and is_owner_user(callback.from_user.id))


def _active_managed_groups() -> list[dict]:
    return [g for g in list_managed_groups(limit=10000) if int(g.get("enabled") or 0) == 1]


def _adeus_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Preparar recuperação", "adeus:prepare", "primary")],
            [_button("Ver recuperação", "adeus:recovery", "primary")],
            [_button("Cancelar", "adeus:cancel", "danger")],
        ]
    )


def _prepared_keyboard(operation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar saída", f"adeus:confirm:{operation_id}", "danger")],
            [_button("Ver pacote de recuperação", f"adeus:recovery:{operation_id}", "primary")],
            [_button("Cancelar", f"adeus:cancel:{operation_id}", "primary")],
        ]
    )


def _confirmed_keyboard(operation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Executar saída agora", f"adeus:execute:{operation_id}", "danger")],
            [_button("Ver pacote de recuperação", f"adeus:recovery:{operation_id}", "primary")],
            [_button("Cancelar", f"adeus:cancel:{operation_id}", "primary")],
        ]
    )


def _recovery_keyboard(operation_id: str | None, items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items[:20]:
        link = item.get("invite_link")
        if not link:
            continue
        label = group_display_name(item.get("title"), "Grupo")
        if len(label) > 46:
            label = label[:43] + "..."
        rows.append([_button(f"Abrir {label}", "adeus:noop", "primary", url=str(link))])
    if operation_id:
        rows.append([_button("Atualizar recuperação", f"adeus:recovery:{operation_id}", "primary")])
    else:
        rows.append([_button("Atualizar recuperação", "adeus:recovery", "primary")])
    rows.append([_button("Fechar", "adeus:cancel", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_text() -> str:
    groups = _active_managed_groups()
    return (
        "Tigrão — saída segura\n\n"
        f"Grupos gerenciados ativos: {len(groups)}\n\n"
        "O bot não sairá imediatamente. Primeiro será criado um pacote de recuperação "
        "com links de convite quando houver permissão para isso.\n\n"
        "A reversão não é automática: depois da saída, será necessário readicionar o bot manualmente."
    )


def _operation_summary(operation: dict) -> str:
    return (
        f"Grupos previstos: {operation.get('total_groups', 0)}\n"
        f"Links criados: {operation.get('prepared_count', 0)}\n"
        f"Falhas ao preparar: {operation.get('failed_prepare_count', 0)}\n"
        f"Saídas concluídas: {operation.get('left_count', 0)}\n"
        f"Falhas ao sair: {operation.get('failed_leave_count', 0)}"
    )


def _recovery_text(operation_id: str | None, items: list[dict]) -> str:
    if not items:
        return "Tigrão — recuperação\n\nNenhum pacote de recuperação encontrado."
    lines = ["Tigrão — recuperação", "", "Grupos com recuperação registrada:", ""]
    for item in items[:30]:
        label = group_display_name(item.get("title"), "Grupo")
        prepare = item.get("prepare_status") or "-"
        leave = item.get("leave_status") or "-"
        rejoin = item.get("rejoin_status") or "pendente"
        has_link = "link disponível" if item.get("invite_link") else "sem link"
        lines.append(f"- {html.escape(label)} — {has_link}; saída={leave}; reentrada={rejoin}; preparo={prepare}")
    lines.append("")
    lines.append("Abra o link do grupo desejado para readicionar o bot. Depois atualize o status no painel.")
    return "\n".join(lines)


@router.message(Command("adeus"))
async def adeus(message: Message) -> None:
    """Owner-only: abre protocolo seguro de saída com recuperação assistida."""
    if not message.from_user or not is_owner_user(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Use /adeus no privado do bot.")
        return
    await message.answer(_home_text(), reply_markup=_adeus_home_keyboard())


@router.message(Command("voltar"))
async def voltar(message: Message) -> None:
    """Owner-only: mostra links de recuperação criados pelo /adeus."""
    if not message.from_user or not is_owner_user(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Use /voltar no privado do bot.")
        return
    operations = list_recovery_operations(limit=1)
    operation_id = operations[0]["operation_id"] if operations else None
    items = list_recovery_items(operation_id, pending_only=False, limit=100) if operation_id else []
    await message.answer(_recovery_text(operation_id, items), reply_markup=_recovery_keyboard(operation_id, items))


@router.callback_query(F.data == "adeus:prepare")
async def adeus_prepare(callback: CallbackQuery) -> None:
    if not _owner_only(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    operation_id = create_recovery_operation(actor_user_id=callback.from_user.id)
    operation = await prepare_recovery_links(callback.bot, operation_id)
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — recuperação preparada\n\n"
            f"{_operation_summary(operation)}\n\n"
            "Revise o pacote. Só grupos com link criado serão elegíveis para saída; falhas ficam bloqueadas por segurança. A próxima etapa apenas confirma; a saída real ainda exige outro toque.",
            reply_markup=_prepared_keyboard(operation_id),
        )
    await callback.answer("Recuperação preparada.")


@router.callback_query(F.data.startswith("adeus:confirm:"))
async def adeus_confirm(callback: CallbackQuery) -> None:
    if not _owner_only(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    operation_id = (callback.data or "").rsplit(":", 1)[-1]
    try:
        confirm_operation(operation_id, actor_user_id=callback.from_user.id)
    except Exception as exc:
        await callback.answer(f"Falha: {type(exc).__name__}", show_alert=True)
        return
    operation = get_operation(operation_id) or {}
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — confirmação crítica\n\n"
            f"{_operation_summary(operation)}\n\n"
            "Ao tocar em Executar saída agora, o bot chamará leaveChat somente nos grupos que possuem link de recuperação preparado. "
            "Essa ação não é reversível automaticamente.",
            reply_markup=_confirmed_keyboard(operation_id),
        )
    await callback.answer("Confirmado. Falta executar.")


@router.callback_query(F.data.startswith("adeus:execute:"))
async def adeus_execute(callback: CallbackQuery) -> None:
    if not _owner_only(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    operation_id = (callback.data or "").rsplit(":", 1)[-1]
    try:
        operation = await execute_leave_operation(callback.bot, operation_id, actor_user_id=callback.from_user.id)
    except Exception as exc:
        await callback.answer(f"Falha: {type(exc).__name__}", show_alert=True)
        return
    items = list_recovery_items(operation_id, pending_only=False, limit=100)
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — saída concluída\n\n"
            f"{_operation_summary(operation)}\n\n"
            "Para reverter, use /voltar ou abra o pacote de recuperação.",
            reply_markup=_recovery_keyboard(operation_id, items),
        )
    await callback.answer("Saída executada.")


@router.callback_query(F.data == "adeus:recovery")
@router.callback_query(F.data.startswith("adeus:recovery:"))
async def adeus_recovery(callback: CallbackQuery) -> None:
    if not _owner_only(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    if callback.data == "adeus:recovery":
        operations = list_recovery_operations(limit=1)
        operation_id = operations[0]["operation_id"] if operations else None
    else:
        operation_id = (callback.data or "").rsplit(":", 1)[-1]
    items = list_recovery_items(operation_id, pending_only=False, limit=100) if operation_id else []
    if callback.message:
        await callback.message.edit_text(_recovery_text(operation_id, items), reply_markup=_recovery_keyboard(operation_id, items))
    await callback.answer()


@router.callback_query(F.data.startswith("adeus:cancel"))
async def adeus_cancel(callback: CallbackQuery) -> None:
    if not _owner_only(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    operation_id = None
    if callback.data and callback.data.startswith("adeus:cancel:"):
        operation_id = callback.data.rsplit(":", 1)[-1]
        try:
            cancel_operation(operation_id, actor_user_id=callback.from_user.id)
        except Exception as exc:
            await callback.answer(f"Falha: {type(exc).__name__}", show_alert=True)
            return
    if callback.message:
        await callback.message.edit_text("Operação /adeus cancelada." + ("\n\nO pacote foi marcado como cancelado." if operation_id else ""))

@router.callback_query(F.data == "adeus:noop")
async def adeus_noop(callback: CallbackQuery) -> None:
    await callback.answer()
