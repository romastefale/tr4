from __future__ import annotations

import json
import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.moderation_tigrao.keyboards import ddx_keyboard, home_keyboard
from app.moderation_tigrao.display import group_display_name
from app.moderation_tigrao.permissions import is_owner_callback, is_owner_private_message
from app.moderation_tigrao.state import clear_action, consume_if_expired, get_session, set_action
from app.moderation_tigrao.storage import get_ddx_filters, load_ddx_words, log_action, set_ddx_filters
from app.moderation_tigrao.texts import error_text, success_text
from app.security.permissions import has_permission

router = Router(name="moderation_tigrao_ddx")


def _has_ddx_permission(user_id: int | None) -> bool:
    session = get_session()
    return bool(session.selected_chat_id and has_permission(user_id, int(session.selected_chat_id), "moderation.ddx.manage"))


async def _deny_if_no_ddx_permission(callback: CallbackQuery) -> bool:
    if _has_ddx_permission(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("Sem permissão DDX neste grupo.", show_alert=True)
    return True



def _selected_group_label() -> str:
    session = get_session()
    return group_display_name(getattr(session, "selected_group_title", None))


def _need_group_text() -> str:
    return error_text(
        "Nenhum grupo selecionado",
        "Você precisa escolher o grupo antes de usar o DDX.",
        "Toque em Escolher grupo e selecione ou digite o chat_id.",
    )


def _parse_words(raw: str) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,;\n]", raw):
        word = re.sub(r"\s+", " ", item.strip().lower())
        if word and word not in seen:
            seen.add(word)
            words.append(word)
    return words


def _ddx_list_text() -> str:
    session = get_session()
    if not session.selected_chat_id:
        return _need_group_text()

    row = get_ddx_filters(int(session.selected_chat_id))
    if not row:
        return (
            "Tigrão — filtros DDX\n\n"
            f"Grupo: {_selected_group_label()}\n\n"
            "Nenhum filtro cadastrado."
        )

    try:
        words = json.loads(str(row.get("words") or "[]"))
    except Exception:
        words = []

    if not isinstance(words, list):
        words = []

    enabled = "ativo" if row.get("enabled") else "inativo"
    words_text = "\n".join(f"- {word}" for word in words) if words else "nenhum"

    return (
        "Tigrão — filtros DDX\n\n"
        f"Grupo: {_selected_group_label()}\n"
        f"Status: {enabled}\n"
        f"Atualizado em: {row.get('updated_at') or '-'}\n\n"
        f"Palavras:\n{words_text}"
    )


@router.callback_query(F.data == "tigrao:ddx:add")
async def tigrao_ddx_add(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return

    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    if await _deny_if_no_ddx_permission(callback):
        return

    set_action("ddx_add", waiting_for="ddx_add_words")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — adicionar filtro DDX\n\n"
            f"Grupo: {_selected_group_label()}\n\n"
            "Envie as palavras ou frases que devem ser filtradas.\n"
            "Pode separar por vírgula, ponto e vírgula ou linha."
        )
    await callback.answer()


@router.message(F.text, lambda message: get_session().waiting_for == "ddx_add_words")
async def tigrao_ddx_receive_add_words(message: Message) -> None:
    if not is_owner_private_message(message):
        return

    # Sprint 7 (T01): guard de expiração.
    if consume_if_expired():
        await message.answer(
            error_text(
                "Sessão expirada",
                "O fluxo de adicionar filtro DDX expirou (15 min).",
                "Use /tigrao para recomeçar.",
            )
        )
        return

    session = get_session()
    if not session.selected_chat_id:
        await message.answer(_need_group_text(), reply_markup=home_keyboard())
        return
    if not _has_ddx_permission(message.from_user.id if message.from_user else None):
        await message.answer(error_text("Sem permissão", "Você não pode alterar DDX neste grupo.", "Peça ao Owner para conceder moderation.ddx.manage."))
        return

    incoming = _parse_words(message.text or "")
    if not incoming:
        await message.answer(
            error_text("Nenhum filtro válido", "Não encontrei palavra ou frase para salvar.", "Envie ao menos uma palavra ou frase."),
            reply_markup=ddx_keyboard(),
        )
        return

    chat_id = int(session.selected_chat_id)
    current = load_ddx_words(chat_id)
    final_words = list(dict.fromkeys(current + incoming))
    set_ddx_filters(chat_id, final_words, enabled=True)
    log_action(chat_id=chat_id, action="ddx_add", status="success")
    clear_action()

    await message.answer(
        success_text(
            "Filtro DDX atualizado",
            f"Grupo: {_selected_group_label()}\nAdicionados: {len(incoming)}\nTotal de filtros: {len(final_words)}",
        ),
        reply_markup=ddx_keyboard(),
    )


@router.callback_query(F.data == "tigrao:ddx:remove")
async def tigrao_ddx_remove(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return

    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    if await _deny_if_no_ddx_permission(callback):
        return

    set_action("ddx_remove", waiting_for="ddx_remove_words")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — remover filtro DDX\n\n"
            f"Grupo: {_selected_group_label()}\n\n"
            "Envie as palavras ou frases que devem ser removidas.\n"
            "Pode separar por vírgula, ponto e vírgula ou linha."
        )
    await callback.answer()


@router.message(F.text, lambda message: get_session().waiting_for == "ddx_remove_words")
async def tigrao_ddx_receive_remove_words(message: Message) -> None:
    if not is_owner_private_message(message):
        return

    # Sprint 7 (T01): guard de expiração.
    if consume_if_expired():
        await message.answer(
            error_text(
                "Sessão expirada",
                "O fluxo de remover filtro DDX expirou (15 min).",
                "Use /tigrao para recomeçar.",
            )
        )
        return

    session = get_session()
    if not session.selected_chat_id:
        await message.answer(_need_group_text(), reply_markup=home_keyboard())
        return
    if not _has_ddx_permission(message.from_user.id if message.from_user else None):
        await message.answer(error_text("Sem permissão", "Você não pode alterar DDX neste grupo.", "Peça ao Owner para conceder moderation.ddx.manage."))
        return

    remove_words = set(_parse_words(message.text or ""))
    if not remove_words:
        await message.answer(
            error_text("Nenhum filtro válido", "Não encontrei palavra ou frase para remover.", "Envie ao menos uma palavra ou frase."),
            reply_markup=ddx_keyboard(),
        )
        return

    chat_id = int(session.selected_chat_id)
    current = load_ddx_words(chat_id)
    final_words = [word for word in current if word not in remove_words]
    removed_count = len(current) - len(final_words)
    set_ddx_filters(chat_id, final_words, enabled=True)
    log_action(chat_id=chat_id, action="ddx_remove", status="success")
    clear_action()

    await message.answer(
        success_text(
            "Filtro DDX atualizado",
            f"Grupo: {_selected_group_label()}\nRemovidos: {removed_count}\nTotal de filtros: {len(final_words)}",
        ),
        reply_markup=ddx_keyboard(),
    )


@router.callback_query(F.data == "tigrao:ddx:off")
async def tigrao_ddx_off(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return

    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    if await _deny_if_no_ddx_permission(callback):
        return

    chat_id = int(session.selected_chat_id)
    current = load_ddx_words(chat_id)
    set_ddx_filters(chat_id, current, enabled=False)
    log_action(chat_id=chat_id, action="ddx_off", status="success")

    if callback.message:
        await callback.message.edit_text(
            success_text(
                "DDX desligado",
                f"Grupo: {_selected_group_label()}\nFiltros preservados: {len(current)}",
            ),
            reply_markup=ddx_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:ddx:list")
async def tigrao_ddx_list(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return

    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    if await _deny_if_no_ddx_permission(callback):
        return

    if callback.message:
        await callback.message.edit_text(_ddx_list_text(), reply_markup=ddx_keyboard())
    await callback.answer()
