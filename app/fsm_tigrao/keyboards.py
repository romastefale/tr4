from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _clip(text: object, limit: int = 48, fallback: str = "Item") -> str:
    value = str(text or "").strip() or fallback
    return value if len(value) <= limit else value[: limit - 1] + "…"


def private_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Moderar por X9", callback_data="tfm:home:mod")],
            [InlineKeyboardButton(text="Configurar grupo", callback_data="tfm:home:grupo")],
            [InlineKeyboardButton(text="Atualizar grupos", callback_data="tfm:home:groups")],
            [InlineKeyboardButton(text="Fechar", callback_data="tfm:home:close")],
        ]
    )


def groups_keyboard(groups: list[dict[str, object]], *, prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups[:20]:
        grp_ref = str(group.get("ui_ref") or "")
        label = _clip(group.get("ui_label") or group.get("titulo") or "Grupo", 44, "Grupo")
        if grp_ref:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"tfm:{prefix}:grp:{grp_ref}")])
    rows.append([InlineKeyboardButton(text="Voltar", callback_data="tfm:home:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def messages_keyboard(messages: list[dict[str, object]], *, grp_ref: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, row in enumerate(messages[:10], start=1):
        msg_ref = str(row.get("msg_ref") or "")
        author = str(row.get("autor_nome") or "membro").strip()
        summary = str(row.get("resumo") or "Mensagem").strip()
        if msg_ref:
            rows.append([InlineKeyboardButton(text=_clip(f"{index}. {author}: {summary}", 58), callback_data=f"tfm:pmod:msg:{msg_ref}")])
    rows.append([InlineKeyboardButton(text="Atualizar mensagens", callback_data=f"tfm:pmod:grp:{grp_ref}")])
    rows.append([InlineKeyboardButton(text="Trocar grupo", callback_data="tfm:home:mod"), InlineKeyboardButton(text="Fechar", callback_data="tfm:home:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mod_action_keyboard(token: str, *, has_author: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Apagar", callback_data=f"tfm:pmod:ask:apagar:{token}"), InlineKeyboardButton(text="Fixar", callback_data=f"tfm:pmod:ask:fixar:{token}")],
        [InlineKeyboardButton(text="Desfixar", callback_data=f"tfm:pmod:ask:desfixar:{token}")],
    ]
    if has_author:
        rows.append([InlineKeyboardButton(text="Banir autor", callback_data=f"tfm:pmod:ask:banir:{token}"), InlineKeyboardButton(text="Silenciar 1h", callback_data=f"tfm:pmod:ask:silenciar:{token}")])
        rows.append([InlineKeyboardButton(text="Apagar + banir", callback_data=f"tfm:pmod:ask:apagar_banir:{token}")])
        rows.append([InlineKeyboardButton(text="Liberar autor", callback_data=f"tfm:pmod:ask:liberar:{token}"), InlineKeyboardButton(text="Reintegrar autor", callback_data=f"tfm:pmod:ask:reintegrar:{token}")])
    rows.append([InlineKeyboardButton(text="Voltar", callback_data="tfm:home:mod"), InlineKeyboardButton(text="Cancelar", callback_data=f"tfm:pmod:cancel:{token}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(action: str, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confirmar no grupo", callback_data=f"tfm:pmod:yes:{action}:{token}")],
            [InlineKeyboardButton(text="Cancelar", callback_data=f"tfm:pmod:cancel:{token}")],
        ]
    )


def group_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Status do bot", callback_data="tfm:pgrp:status")],
            [InlineKeyboardButton(text="Convite com aprovação", callback_data="tfm:pgrp:convite")],
            [InlineKeyboardButton(text="DDX", callback_data="tfm:pgrp:ddx"), InlineKeyboardButton(text="Logs recentes", callback_data="tfm:pgrp:logs")],
            [InlineKeyboardButton(text="Trocar grupo", callback_data="tfm:home:grupo"), InlineKeyboardButton(text="Fechar", callback_data="tfm:home:close")],
        ]
    )


def ddx_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Adicionar palavra", callback_data="tfm:pgrp:ddx_add"), InlineKeyboardButton(text="Remover palavra", callback_data="tfm:pgrp:ddx_del")],
            [InlineKeyboardButton(text="Ativar", callback_data="tfm:pgrp:ddx_on"), InlineKeyboardButton(text="Pausar", callback_data="tfm:pgrp:ddx_off")],
            [InlineKeyboardButton(text="Voltar", callback_data="tfm:pgrp:panel")],
        ]
    )
