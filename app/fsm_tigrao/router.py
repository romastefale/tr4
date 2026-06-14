from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.equalizador.ddx import DDX_HARD_MODE, list_ddx_publico, salvar_ddx_config
from app.equalizador.mesa import executar_ajuste, list_historico_publico, mesa_error_public_detail
from app.fsm_tigrao.context import (
    chat_is_group,
    chat_is_private,
    get_group_by_ref,
    get_message_by_ref,
    is_operator_user,
    list_known_groups,
    list_recent_messages,
    record_group_message_context,
    upsert_context_operator,
    upsert_context_palco,
    user_can_operate_group,
)
from app.fsm_tigrao.keyboards import (
    confirm_keyboard,
    ddx_keyboard,
    group_panel_keyboard,
    groups_keyboard,
    messages_keyboard,
    mod_action_keyboard,
    private_home_keyboard,
)

router = Router(name="fsm_tigrao_private_x9")
logger = logging.getLogger(__name__)

# Fase 12B rule / Fase 12B+ rule: group messages may feed X9 context, but all operational menus,
# confirmations, errors and actions are private DM only. Fase 13A adds TR3 parity
# actions only to the private FSM, never to group-visible replies.
_TOKENS: dict[str, dict[str, Any]] = {}
_SESSIONS: dict[int, dict[str, Any]] = {}
_TOKEN_TTL_SECONDS = 20 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_tokens() -> None:
    cutoff = _now() - timedelta(seconds=_TOKEN_TTL_SECONDS)
    for key, row in list(_TOKENS.items()):
        created_at = row.get("created_at")
        if not isinstance(created_at, datetime) or created_at < cutoff:
            _TOKENS.pop(key, None)


def _new_token(payload: dict[str, Any], *, user_id: int) -> str:
    _cleanup_tokens()
    token = secrets.token_urlsafe(12).replace("-", "_")[:16]
    payload["created_at"] = _now()
    payload["user_id"] = int(user_id)
    _TOKENS[token] = payload
    return token


def _token_payload(token: str, *, user_id: int | None = None) -> dict[str, Any] | None:
    _cleanup_tokens()
    payload = _TOKENS.get(str(token or ""))
    if not payload:
        return None
    if user_id is not None and int(payload.get("user_id") or 0) != int(user_id):
        return None
    return payload


def _session(user_id: int) -> dict[str, Any]:
    row = _SESSIONS.setdefault(int(user_id), {"updated_at": _now()})
    row["updated_at"] = _now()
    return row


def _selected_palco(user_id: int) -> dict[str, object] | None:
    grp_ref = _session(user_id).get("grp_ref")
    if not grp_ref:
        return None
    return get_group_by_ref(grp_ref=str(grp_ref))


def _hard_filter(ddx: dict[str, Any]) -> dict[str, Any]:
    filtros = ddx.get("filtros") if isinstance(ddx, dict) else []
    for row in filtros if isinstance(filtros, list) else []:
        if isinstance(row, dict) and row.get("modo") == DDX_HARD_MODE:
            return row
    return {"palavras": [], "enabled": False}


def _action_label(action: str) -> str:
    return {
        "apagar": "apagar mensagem",
        "fixar": "fixar mensagem",
        "desfixar": "desfixar mensagem",
        "banir": "banir autor",
        "silenciar": "silenciar autor por 1 hora",
        "liberar": "liberar autor",
        "reintegrar": "reintegrar autor",
        "apagar_banir": "apagar mensagem e banir autor",
    }.get(action, action)


def _ajuste_for_action(action: str) -> str:
    return {
        "apagar": "mensagens.apagar",
        "fixar": "fixados.criar",
        "desfixar": "fixados.remover",
        "banir": "membros.remover",
        "silenciar": "membros.silenciar",
        "liberar": "membros.liberar",
        "reintegrar": "membros.reintegrar",
    }[action]


def _payload_for_action(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in {"apagar", "fixar", "desfixar"}:
        return {"msg_ref": data["msg_ref"], "sem_notificacao": True}
    if action == "banir":
        return {"alvo_ref": data["alvo_ref"], "revogar_mensagens": True}
    if action == "silenciar":
        return {"alvo_ref": data["alvo_ref"], "duracao_segundos": 3600}
    if action == "liberar":
        return {"alvo_ref": data["alvo_ref"]}
    if action == "reintegrar":
        return {"alvo_ref": data["alvo_ref"], "apenas_se_banido": True}
    raise ValueError("acao_indisponivel")




def _requires_author(action: str) -> bool:
    return action in {"banir", "silenciar", "liberar", "reintegrar", "apagar_banir"}


def _requires_message(action: str) -> bool:
    return action in {"apagar", "fixar", "desfixar", "apagar_banir"}

def _private_allowed(user_id: int | None) -> bool:
    return is_operator_user(user_id)


async def _ensure_private_operator_for_palco(bot: Any, *, user_id: int | None, palco: dict[str, object] | None) -> bool:
    if user_id is None or palco is None:
        return False
    if _private_allowed(int(user_id)):
        return True
    return await user_can_operate_group(bot, chat_id=int(palco["telegram_chat_id"]), user_id=int(user_id))


async def _silent_group_capture(message: Message) -> None:
    """Capture group context without displaying action menus in the group.

    Fase 12E: a group trigger never enrolls an unknown group merely because
    the sender is a Telegram chat admin. Unknown-group enrollment by trigger is
    reserved for configured TR4 operators/owners. Regular chat admins may still
    have their trigger deleted silently, but they do not receive DM references and
    do not create private-FSM scope.
    """
    try:
        user_id = int(message.from_user.id) if message.from_user else None
        configured_actor = _private_allowed(user_id)
        if configured_actor:
            record_group_message_context(message.reply_to_message or message, allow_unknown_group=True)
            try:
                await message.bot.send_message(
                    int(user_id),
                    "Contexto capturado pelo X9. Abra /tmod aqui no privado para agir sem expor menu no grupo.",
                )
            except Exception:
                logger.debug("X9_PRIVATE_NOTICE_FAILED", exc_info=True)
        try:
            await message.delete()
        except Exception:
            logger.debug("X9_TRIGGER_DELETE_FAILED", exc_info=True)
    except Exception:
        logger.debug("X9_GROUP_CAPTURE_FAILED", exc_info=True)


def _is_private_waiting_ddx(message: Message) -> bool:
    if not message.from_user or not chat_is_private(message.chat):
        return False
    if not _private_allowed(int(message.from_user.id)):
        return False
    return _session(int(message.from_user.id)).get("waiting_for") in {"ddx_add", "ddx_del"}


def _groups_text(kind: str) -> str:
    if kind == "mod":
        return (
            "<b>Moderação privada por X9</b>\n\n"
            "Escolha um grupo observado. As ações e confirmações ficam somente aqui no privado."
        )
    return (
        "<b>Configuração privada de grupo</b>\n\n"
        "Escolha o grupo que será configurado. Nada é mostrado no grupo."
    )


async def _send_private_home(message: Message) -> None:
    await message.answer(
        "<b>Tigrão privado</b>\n\n"
        "O Web App fica só como player. Moderação e configuração acontecem aqui no privado, usando o X9 para contexto dos grupos.",
        reply_markup=private_home_keyboard(),
    )


@router.message(Command("tmod", "mod"))
async def mod_command(message: Message) -> None:
    if not message.from_user:
        return
    if chat_is_group(message.chat):
        await _silent_group_capture(message)
        return
    if not chat_is_private(message.chat):
        return
    if not _private_allowed(int(message.from_user.id)):
        await message.answer("Acesso negado. Peça ao dono para habilitar seu usuário como operador.")
        return
    upsert_context_operator(user=message.from_user, perfil="Moderador")
    groups = list_known_groups(limit=20)
    if not groups:
        await message.answer("Nenhum grupo observado ainda. O X9 precisa ver mensagens nos grupos onde o bot atua.")
        return
    await message.answer(_groups_text("mod"), reply_markup=groups_keyboard(groups, prefix="pmod"))


@router.message(Command("tgrp", "grupo"))
async def grupo_command(message: Message) -> None:
    if not message.from_user:
        return
    if chat_is_group(message.chat):
        await _silent_group_capture(message)
        return
    if not chat_is_private(message.chat):
        return
    if not _private_allowed(int(message.from_user.id)):
        await message.answer("Acesso negado. Peça ao dono para habilitar seu usuário como operador.")
        return
    upsert_context_operator(user=message.from_user, perfil="Moderador")
    groups = list_known_groups(limit=20)
    if not groups:
        await message.answer("Nenhum grupo observado ainda. O X9 precisa ver mensagens nos grupos onde o bot atua.")
        return
    await message.answer(_groups_text("grupo"), reply_markup=groups_keyboard(groups, prefix="pgrp"))


@router.message(Command("tadd", "tdel", "ddxadd", "ddxdel"))
async def ddx_command(message: Message) -> None:
    if not message.from_user:
        return
    if chat_is_group(message.chat):
        await _silent_group_capture(message)
        return
    if not chat_is_private(message.chat):
        return
    if not _private_allowed(int(message.from_user.id)):
        await message.answer("Acesso negado.")
        return
    palco = _selected_palco(int(message.from_user.id))
    if not palco:
        await message.answer("Escolha um grupo primeiro com /tgrp.")
        return
    if not await _ensure_private_operator_for_palco(message.bot, user_id=int(message.from_user.id), palco=palco):
        await message.answer("Acesso negado para este grupo.")
        return
    command = (message.text or "").split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()
    word = ((message.text or "").split(maxsplit=1)[1] if len((message.text or "").split(maxsplit=1)) > 1 else "").strip()[:80]
    if not word or "<" in word or ">" in word:
        await message.answer(f"Envie assim: /{command} palavra ou frase")
        return
    ator = upsert_context_operator(user=message.from_user, perfil="Moderador")
    ddx = list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())
    hard = _hard_filter(ddx)
    words = list(hard.get("palavras", [])) if isinstance(hard, dict) else []
    if command in {"tadd", "ddxadd"}:
        if word.lower() not in {str(item).lower() for item in words}:
            words.append(word)
        enabled = True
        verb = "adicionada"
    elif command in {"tdel", "ddxdel"}:
        words = [item for item in words if str(item).lower() != word.lower()]
        enabled = bool(words)
        verb = "removida"
    else:
        await message.answer("Comando DDX inválido. Use /tadd ou /tdel no privado.")
        return
    salvar_ddx_config(palco=palco, ator_ref=str(ator["usr_ref"]), mode=DDX_HARD_MODE, words=words, enabled=enabled, alias_secret=settings.equalizador_alias_secret())
    await message.answer(f"DDX atualizado no grupo selecionado. Palavra/frase {verb}: <code>{html.escape(word)}</code>")


@router.message(Command("start"))
async def private_start(message: Message) -> None:
    if message.from_user and chat_is_private(message.chat) and _private_allowed(int(message.from_user.id)):
        await _send_private_home(message)


@router.callback_query(F.data.startswith("tfm:home:"))
async def home_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    if not _private_allowed(int(callback.from_user.id)):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    action = str(callback.data or "").split(":", 2)[2]
    if action == "close":
        await callback.message.edit_text("Painel privado fechado.")
        await callback.answer()
        return
    if action == "start":
        await callback.message.edit_text(
            "<b>Tigrão privado</b>\n\nEscolha uma área.",
            reply_markup=private_home_keyboard(),
        )
        await callback.answer()
        return
    if action in {"groups", "mod"}:
        groups = list_known_groups(limit=20)
        await callback.message.edit_text(_groups_text("mod"), reply_markup=groups_keyboard(groups, prefix="pmod"))
        await callback.answer()
        return
    if action == "grupo":
        groups = list_known_groups(limit=20)
        await callback.message.edit_text(_groups_text("grupo"), reply_markup=groups_keyboard(groups, prefix="pgrp"))
        await callback.answer()
        return
    await callback.answer("Ação indisponível.", show_alert=True)


@router.callback_query(F.data.startswith("tfm:pmod:grp:"))
async def pmod_group_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    grp_ref = str(callback.data or "").rsplit(":", 1)[-1]
    palco = get_group_by_ref(grp_ref=grp_ref)
    if not palco:
        await callback.answer("Grupo indisponível.", show_alert=True)
        return
    if not await _ensure_private_operator_for_palco(callback.message.bot, user_id=int(callback.from_user.id), palco=palco):
        await callback.answer("Acesso negado para este grupo.", show_alert=True)
        return
    _session(int(callback.from_user.id))["grp_ref"] = grp_ref
    messages = list_recent_messages(chat_id=int(palco["telegram_chat_id"]), limit=10)
    if not messages:
        await callback.message.edit_text(
            "<b>X9 sem mensagens recentes</b>\n\n"
            "O X9 ainda não tem mensagens operáveis desse grupo. Ele só retém contexto recente, autorizado e dentro da janela operacional.",
            reply_markup=groups_keyboard(list_known_groups(limit=20), prefix="pmod"),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"<b>Mensagens recentes — {html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}</b>\n\n"
        "Escolha a mensagem para agir em privado.",
        reply_markup=messages_keyboard(messages, grp_ref=grp_ref),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tfm:pmod:msg:"))
async def pmod_message_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    msg_ref = str(callback.data or "").rsplit(":", 1)[-1]
    msg = get_message_by_ref(msg_ref=msg_ref)
    if not msg:
        await callback.answer("Mensagem indisponível.", show_alert=True)
        return
    palco = _selected_palco(int(callback.from_user.id)) or get_group_by_ref(grp_ref=str(_session(int(callback.from_user.id)).get("grp_ref") or ""))
    if not palco or int(palco["telegram_chat_id"]) != int(msg["telegram_chat_id"]):
        await callback.answer("Selecione o grupo novamente.", show_alert=True)
        return
    if not await _ensure_private_operator_for_palco(callback.message.bot, user_id=int(callback.from_user.id), palco=palco):
        await callback.answer("Acesso negado para este grupo.", show_alert=True)
        return
    ator = upsert_context_operator(user=callback.from_user, perfil="Moderador")
    token = _new_token(
        {
            "palco": palco,
            "ator_ref": str(ator["usr_ref"]),
            "msg_ref": msg_ref,
            "alvo_ref": msg.get("autor_ref"),
            "summary": str(msg.get("resumo") or "Mensagem"),
            "author": str(msg.get("autor_nome") or "membro"),
        },
        user_id=int(callback.from_user.id),
    )
    await callback.message.edit_text(
        "<b>Moderação privada por X9</b>\n\n"
        f"Grupo: {html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}\n"
        f"Autor: {html.escape(str(msg.get('autor_nome') or 'autor não registrado'))}\n"
        f"Mensagem: {html.escape(str(msg.get('resumo') or 'Mensagem'))}\n\n"
        "Escolha a ação. Nada será mostrado como menu no grupo.",
        reply_markup=mod_action_keyboard(token, has_author=bool(msg.get("autor_ref"))),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tfm:pmod:"))
async def pmod_action_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer("Ação inválida.", show_alert=True)
        return
    step = parts[2]
    if step == "cancel":
        token = parts[3]
        data = _token_payload(token, user_id=int(callback.from_user.id))
        if data:
            _TOKENS.pop(token, None)
        await callback.message.edit_text("Moderação privada cancelada.")
        await callback.answer()
        return
    if len(parts) != 5:
        await callback.answer("Ação inválida.", show_alert=True)
        return
    action = parts[3]
    token = parts[4]
    data = _token_payload(token, user_id=int(callback.from_user.id))
    if not data:
        await callback.answer("Ação expirada ou vinculada a outro usuário. Use /tmod no privado novamente.", show_alert=True)
        return
    palco = data.get("palco") if isinstance(data.get("palco"), dict) else None
    if not await _ensure_private_operator_for_palco(callback.message.bot, user_id=int(callback.from_user.id), palco=palco):
        await callback.answer("Acesso negado para este grupo.", show_alert=True)
        return
    if _requires_author(action) and not data.get("alvo_ref"):
        await callback.answer("Não há autor seguro para esta ação.", show_alert=True)
        return
    if _requires_message(action) and not data.get("msg_ref"):
        await callback.answer("Não há mensagem segura para esta ação.", show_alert=True)
        return
    if step == "ask":
        data["pending_action"] = action
        await callback.message.edit_text(
            "<b>Confirmar ação privada</b>\n\n"
            f"Grupo: {html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}\n"
            f"Ação: {html.escape(_action_label(action))}\n"
            f"Mensagem: {html.escape(str(data.get('summary') or 'Mensagem'))}\n\n"
            "A execução afetará o grupo, mas o menu e o retorno permanecem somente aqui.",
            reply_markup=confirm_keyboard(action, token),
        )
        await callback.answer()
        return
    if step != "yes":
        await callback.answer("Ação inválida.", show_alert=True)
        return
    if str(data.get("pending_action") or "") != action:
        await callback.answer("Confirmação inválida. Recomece em /tmod.", show_alert=True)
        return
    try:
        if action == "apagar_banir":
            first = await executar_ajuste(
                ajuste="mensagens.apagar",
                palco=palco,
                ator_ref=str(data["ator_ref"]),
                payload={"msg_ref": data["msg_ref"], "sem_notificacao": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
            second = await executar_ajuste(
                ajuste="membros.remover",
                palco=palco,
                ator_ref=str(data["ator_ref"]),
                payload={"alvo_ref": data["alvo_ref"], "revogar_mensagens": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
            resumo = f"{first.get('resumo') or 'Mensagem apagada'}; {second.get('resumo') or 'autor banido'}"
            result = {"resumo": resumo}
        else:
            result = await executar_ajuste(
                ajuste=_ajuste_for_action(action),
                palco=palco,
                ator_ref=str(data["ator_ref"]),
                payload=_payload_for_action(action, data),
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        _TOKENS.pop(token, None)
        await callback.message.edit_text("<b>Moderação concluída</b>\n\n" + html.escape(str(result.get("resumo") or "Ação executada.")))
        await callback.answer("Concluído.")
    except Exception as exc:
        await callback.message.edit_text("<b>Moderação não concluída</b>\n\n" + html.escape(mesa_error_public_detail(exc)))
        await callback.answer("Falhou.", show_alert=True)


@router.callback_query(F.data.startswith("tfm:pgrp:grp:"))
async def pgrp_group_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    grp_ref = str(callback.data or "").rsplit(":", 1)[-1]
    palco = get_group_by_ref(grp_ref=grp_ref)
    if not palco:
        await callback.answer("Grupo indisponível.", show_alert=True)
        return
    if not await _ensure_private_operator_for_palco(callback.message.bot, user_id=int(callback.from_user.id), palco=palco):
        await callback.answer("Acesso negado para este grupo.", show_alert=True)
        return
    _session(int(callback.from_user.id))["grp_ref"] = grp_ref
    await callback.message.edit_text(
        f"<b>Grupo selecionado</b>\n\n{html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}\n\n"
        "Configure pelo privado. Nada será mostrado no grupo.",
        reply_markup=group_panel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tfm:pgrp:"))
async def pgrp_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user or not chat_is_private(callback.message.chat):
        await callback.answer("Abra no privado.", show_alert=True)
        return
    user_id = int(callback.from_user.id)
    palco = _selected_palco(user_id)
    if not palco:
        await callback.answer("Escolha o grupo primeiro.", show_alert=True)
        return
    if not await _ensure_private_operator_for_palco(callback.message.bot, user_id=user_id, palco=palco):
        await callback.answer("Acesso negado para este grupo.", show_alert=True)
        return
    action = str(callback.data or "").split(":", 2)[2]
    ator = upsert_context_operator(user=callback.from_user, perfil="Moderador")
    if action == "panel":
        await callback.message.edit_text(
            f"<b>Grupo selecionado</b>\n\n{html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}",
            reply_markup=group_panel_keyboard(),
        )
        await callback.answer()
        return
    if action == "status":
        try:
            me = await callback.message.bot.get_me()
            member = await callback.message.bot.get_chat_member(int(palco["telegram_chat_id"]), int(me.id))
            status = html.escape(str(getattr(member, "status", "desconhecido")))
            await callback.message.edit_text(
                "<b>Status do bot no grupo</b>\n\n"
                f"Grupo: {html.escape(str(palco.get('ui_label') or palco.get('titulo') or 'Grupo'))}\n"
                f"Estado: {status}\n"
                "As permissões reais são verificadas antes de cada ação.",
                reply_markup=group_panel_keyboard(),
            )
        except Exception:
            await callback.message.edit_text("Não consegui ler o status do bot agora.", reply_markup=group_panel_keyboard())
        await callback.answer()
        return
    if action == "convite":
        try:
            result = await executar_ajuste(
                ajuste="convites.criar",
                palco=palco,
                ator_ref=str(ator["usr_ref"]),
                payload={"nome": "Convite privado com aprovação", "solicitar_aprovacao": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
            link = html.escape(str(result.get("convite") or ""))
            await callback.message.edit_text(
                "<b>Convite criado em privado</b>\n\n"
                f"{link or 'Link indisponível no retorno.'}\n\n"
                "Entradas exigem aprovação.",
                reply_markup=group_panel_keyboard(),
            )
        except Exception as exc:
            await callback.message.edit_text("<b>Convite não criado</b>\n\n" + html.escape(mesa_error_public_detail(exc)), reply_markup=group_panel_keyboard())
        await callback.answer()
        return
    if action == "logs":
        rows = list_historico_publico(palco_refs={str(palco["ui_ref"])}, limit=8)
        lines = [
            "<b>Logs recentes do grupo</b>",
            html.escape(str(palco.get("ui_label") or palco.get("titulo") or "Grupo")),
            "",
        ]
        if not rows:
            lines.append("Nenhum log recente para este grupo.")
        for row in rows:
            lines.append(
                "• "
                + html.escape(str(row.get("created_at") or ""))
                + " · "
                + html.escape(str(row.get("ajuste") or "ação"))
                + " · "
                + html.escape(str(row.get("status") or "status"))
                + " · "
                + html.escape(str(row.get("resumo") or row.get("resumo_publico") or ""))
            )
        await callback.message.edit_text("\n".join(lines)[:3900], reply_markup=group_panel_keyboard())
        await callback.answer()
        return

    if action == "ddx":
        ddx = list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())
        hard = _hard_filter(ddx)
        words = hard.get("palavras", []) if isinstance(hard, dict) else []
        enabled = bool(hard.get("enabled")) if isinstance(hard, dict) else False
        await callback.message.edit_text(
            "<b>DDX privado do grupo</b>\n\n"
            f"Estado: {'ativo' if enabled else 'pausado'}\n"
            f"Palavras: {len(words)}" + ("\n" + html.escape(", ".join(str(w) for w in words[:8])) if words else "") + "\n\n"
            "Use os botões ou envie /tadd e /tdel aqui no privado.",
            reply_markup=ddx_keyboard(),
        )
        await callback.answer()
        return
    if action in {"ddx_on", "ddx_off"}:
        ddx = list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())
        hard = _hard_filter(ddx)
        words = list(hard.get("palavras", [])) if isinstance(hard, dict) else []
        salvar_ddx_config(palco=palco, ator_ref=str(ator["usr_ref"]), mode=DDX_HARD_MODE, words=words, enabled=(action == "ddx_on"), alias_secret=settings.equalizador_alias_secret())
        await callback.message.edit_text(f"DDX {'ativado' if action == 'ddx_on' else 'pausado'} para o grupo selecionado.", reply_markup=group_panel_keyboard())
        await callback.answer()
        return
    if action in {"ddx_add", "ddx_del"}:
        _session(user_id)["waiting_for"] = action
        await callback.message.edit_text(
            "Envie agora a palavra ou frase para " + ("adicionar" if action == "ddx_add" else "remover") + " do DDX.",
            reply_markup=ddx_keyboard(),
        )
        await callback.answer()
        return
    await callback.answer("Ação indisponível.", show_alert=True)


@router.message(F.text, _is_private_waiting_ddx)
async def private_waiting_text(message: Message) -> None:
    if not message.from_user or not chat_is_private(message.chat):
        return
    user_id = int(message.from_user.id)
    if not _private_allowed(user_id):
        return
    waiting = _session(user_id).get("waiting_for")
    if waiting not in {"ddx_add", "ddx_del"}:
        return
    palco = _selected_palco(user_id)
    if not palco:
        await message.answer("Escolha um grupo primeiro com /tgrp.")
        return
    word = (message.text or "").strip()[:80]
    if not word or "<" in word or ">" in word:
        await message.answer("Texto inválido para DDX.")
        return
    ator = upsert_context_operator(user=message.from_user, perfil="Moderador")
    ddx = list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())
    hard = _hard_filter(ddx)
    words = list(hard.get("palavras", [])) if isinstance(hard, dict) else []
    if waiting == "ddx_add":
        if word.lower() not in {str(item).lower() for item in words}:
            words.append(word)
        enabled = True
        verb = "adicionada"
    else:
        words = [item for item in words if str(item).lower() != word.lower()]
        enabled = bool(words)
        verb = "removida"
    salvar_ddx_config(palco=palco, ator_ref=str(ator["usr_ref"]), mode=DDX_HARD_MODE, words=words, enabled=enabled, alias_secret=settings.equalizador_alias_secret())
    _session(user_id).pop("waiting_for", None)
    await message.answer(f"DDX atualizado. Palavra/frase {verb}: <code>{html.escape(word)}</code>", reply_markup=group_panel_keyboard())
