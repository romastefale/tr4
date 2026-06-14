from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.db.database import engine
from app.equalizador.admin import executar_admin_critico
from app.equalizador.avancado import avancado_error_public_detail, executar_ajuste_avancado
from app.equalizador.maestro import MAESTRO_CONFIRMATION_PHRASE
from app.equalizador.mesa import ensure_bot_right, executar_ajuste, mesa_error_public_detail, record_historico, register_mensagem_ref, telegram_api_call
from app.equalizador.palcos import get_palco_internal_by_ref, list_equalizador_palcos
from app.fsm_tigrao.context import list_recent_messages, upsert_context_operator

router = Router(name="tgov_owner")
logger = logging.getLogger(__name__)

_STATE: dict[int, dict[str, Any]] = {}


def _owner_allowed(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET


def _state(user_id: int) -> dict[str, Any]:
    return _STATE.setdefault(int(user_id), {})


def _keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _safe(value: object, fallback: str = "") -> str:
    return html.escape(str(value or fallback))


def _groups() -> list[dict[str, object]]:
    return list_equalizador_palcos(
        palco_ids=settings.equalizador_allowed_palco_ids(),
        alias_secret=settings.equalizador_alias_secret(),
    )[:20]


def _selected_palco(user_id: int) -> dict[str, Any] | None:
    grp_ref = str(_state(user_id).get("grp_ref") or "")
    if not grp_ref:
        return None
    return get_palco_internal_by_ref(grp_ref=grp_ref)


def _actor_ref(user_id: int) -> str:
    return f"owner:{int(user_id)}"


def _home_text(user_id: int) -> str:
    palco = _selected_palco(user_id)
    group = str((palco or {}).get("titulo") or _state(user_id).get("grp_label") or "grupo não escolhido")
    return (
        "<b>/tgov — governo owner</b>\n"
        "Comando novo, só no privado do dono, para ações avançadas do grupo.\n\n"
        f"Grupo: {_safe(group)}\n\n"
        "Aqui ficam nome, descrição, foto, publicação nativa por cópia e tag de membro. "
        "Nada aparece como menu no grupo."
    )


def _groups_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in _groups():
        ref = str(row.get("grp_ref") or "")
        label = str(row.get("titulo") or row.get("alias") or "Grupo")[:40]
        if ref:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"tgov:g:{ref}")])
    rows.append([InlineKeyboardButton(text="Fechar", callback_data="tgov:close")])
    return _keyboard(rows)


def _home_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [InlineKeyboardButton(text="Escolher grupo", callback_data="tgov:groups")],
        [InlineKeyboardButton(text="Nome do grupo", callback_data="tgov:ask:title"), InlineKeyboardButton(text="Descrição", callback_data="tgov:ask:description")],
        [InlineKeyboardButton(text="Remover foto", callback_data="tgov:ask:photo_remove")],
        [InlineKeyboardButton(text="Enviar post nativo", callback_data="tgov:ask:post_copy")],
        [InlineKeyboardButton(text="Texto simples", callback_data="tgov:ask:send_text"), InlineKeyboardButton(text="Foto/link legado", callback_data="tgov:ask:send_photo")],
        [InlineKeyboardButton(text="Tag de membro", callback_data="tgov:tag_messages")],
        [InlineKeyboardButton(text="Fechar", callback_data="tgov:close")],
    ])


def _tag_messages_keyboard(user_id: int) -> InlineKeyboardMarkup:
    palco = _selected_palco(user_id)
    rows: list[list[InlineKeyboardButton]] = []
    if palco:
        messages = list_recent_messages(chat_id=int(palco["telegram_chat_id"]), limit=8)
        for idx, row in enumerate(messages, start=1):
            msg_ref = str(row.get("msg_ref") or "")
            autor = str(row.get("autor_nome") or "membro")
            if msg_ref and row.get("autor_ref"):
                rows.append([InlineKeyboardButton(text=f"{idx}. {autor}"[:48], callback_data=f"tgov:tag_msg:{msg_ref}")])
    rows.append([InlineKeyboardButton(text="Voltar", callback_data="tgov:home")])
    return _keyboard(rows)


def _post_confirm_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [InlineKeyboardButton(text="Publicar", callback_data="tgov:post:send")],
        [InlineKeyboardButton(text="Publicar e fixar em silêncio", callback_data="tgov:post:send_pin_silent")],
        [InlineKeyboardButton(text="Cancelar", callback_data="tgov:post:cancel")],
    ])


def _post_kind_label(message: Message) -> str:
    if getattr(message, "photo", None):
        return "foto"
    if getattr(message, "video", None):
        return "vídeo"
    if getattr(message, "animation", None):
        return "animação"
    if getattr(message, "document", None):
        return "documento"
    if getattr(message, "audio", None):
        return "áudio"
    if getattr(message, "voice", None):
        return "voz"
    if getattr(message, "video_note", None):
        return "vídeo circular"
    if getattr(message, "sticker", None):
        return "sticker"
    if getattr(message, "poll", None):
        return "enquete"
    if getattr(message, "contact", None):
        return "contato"
    if getattr(message, "location", None):
        return "localização"
    if getattr(message, "venue", None):
        return "local"
    if getattr(message, "text", None):
        return "texto"
    return "mensagem"




def _copy_messages_result_ids(result: object) -> list[int]:
    if isinstance(result, dict):
        result = [result]
    ids: list[int] = []
    if isinstance(result, list):
        for item in result:
            value = getattr(item, "message_id", None)
            if value is None and isinstance(item, dict):
                value = item.get("message_id")
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    return ids


def _pending_message_ids(pending: dict[str, object]) -> list[int]:
    raw_ids = pending.get("message_ids")
    ids: list[int] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    if not ids:
        try:
            ids.append(int(pending["message_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    # Telegram exige ordem crescente para preservar álbum sem duplicar.
    return sorted(dict.fromkeys(ids))


def _album_item_count_text(total: int) -> str:
    if total <= 1:
        return "1 item recebido"
    return f"{total} itens recebidos"

def _copy_result_message_id(result: object) -> int | None:
    value = getattr(result, "message_id", None)
    if value is None and isinstance(result, dict):
        value = result.get("message_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _publish_pending_post(*, callback: CallbackQuery, user_id: int, fixar_silencioso: bool) -> dict[str, object]:
    state = _state(user_id)
    pending = state.get("pending_post") if isinstance(state.get("pending_post"), dict) else None
    palco = _selected_palco(user_id)
    if not pending or not palco:
        raise RuntimeError("Post pendente indisponível.")
    if not callback.message:
        raise RuntimeError("Mensagem de confirmação indisponível.")
    chat_id = int(palco["telegram_chat_id"])
    source_message_ids = _pending_message_ids(pending)
    if not source_message_ids:
        raise RuntimeError("Mensagem pendente indisponível.")
    if len(source_message_ids) > 1:
        result = await telegram_api_call(
            settings.TELEGRAM_BOT_TOKEN,
            "copyMessages",
            {
                "chat_id": chat_id,
                "from_chat_id": int(pending["from_chat_id"]),
                "message_ids": source_message_ids,
                "disable_notification": True,
            },
        )
        published_message_ids = _copy_messages_result_ids(result)
        method = "copyMessages"
    else:
        sent = await callback.message.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=int(pending["from_chat_id"]),
            message_id=int(source_message_ids[0]),
            disable_notification=True,
        )
        first_id = _copy_result_message_id(sent)
        published_message_ids = [first_id] if first_id is not None else []
        method = "copyMessage"
    if not published_message_ids:
        raise RuntimeError("Telegram não retornou o ID da mensagem copiada.")
    msg_refs: list[str] = []
    for idx, published_id in enumerate(published_message_ids, start=1):
        msg_refs.append(register_mensagem_ref(
            chat_id=chat_id,
            message_id=published_id,
            resumo_publico=str(pending.get("resumo") or "Post copiado")[:140] + (f" ({idx}/{len(published_message_ids)})" if len(published_message_ids) > 1 else ""),
            alias_secret=settings.equalizador_alias_secret(),
            db_engine=engine,
        ))
    message_id = int(published_message_ids[0])
    msg_ref = msg_refs[0]
    fixacao: dict[str, object] | None = None
    if fixar_silencioso:
        try:
            await ensure_bot_right(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=chat_id,
                required_right="can_pin_messages",
            )
            await callback.message.bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
            fixacao = {"ok": True, "silenciosa": True, "message_id": message_id}
        except Exception as exc:
            fixacao = {"ok": False, "motivo": mesa_error_public_detail(exc)}
    historico = record_historico(
        ator_ref=_actor_ref(user_id),
        palco_ref=str(palco["ui_ref"]),
        alvo_ref=msg_ref,
        ajuste="mensagens.copiar_post",
        status="concluido",
        resumo_publico=f"Post copiado para {palco.get('titulo') or 'Grupo'}",
        payload_tecnico={
            "method": "copyMessage" if method == "copyMessage" else "copyMessages",
            "source": "owner_dm",
            "tipo": pending.get("tipo"),
            "media_group_id": pending.get("media_group_id"),
            "source_message_ids": source_message_ids,
            "published_message_ids": published_message_ids,
            "msg_refs": msg_refs,
            "fixacao": fixacao,
        },
        alias_secret=settings.equalizador_alias_secret(),
        db_engine=engine,
    )
    state.pop("pending_post", None)
    state.pop("awaiting", None)
    return {"ok": True, "msg_ref": msg_ref, "msg_refs": msg_refs, "historico": historico, "fixacao": fixacao, "method": method}


@router.message(Command("tgov"))
async def tgov_command(message: Message) -> None:
    if not message.from_user:
        return
    if message.chat.type != "private":
        # Owner command; no group-visible control surface.
        try:
            await message.delete()
        except Exception:
            pass
        return
    user_id = int(message.from_user.id)
    if not _owner_allowed(user_id):
        await message.answer("Acesso indisponível.")
        return
    if not _selected_palco(user_id):
        await message.answer("<b>/tgov — escolha o grupo</b>", reply_markup=_groups_keyboard(), parse_mode="HTML")
        return
    await message.answer(_home_text(user_id), reply_markup=_home_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.startswith("tgov:"))
async def tgov_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not _owner_allowed(int(callback.from_user.id)):
        await callback.answer("Acesso indisponível.", show_alert=True)
        return
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Abra no privado.", show_alert=True)
        return
    user_id = int(callback.from_user.id)
    data = str(callback.data or "")
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"
    try:
        if action == "close":
            await callback.message.edit_text("/tgov fechado.")
            await callback.answer()
            return
        if action == "home":
            await callback.message.edit_text(_home_text(user_id), reply_markup=_home_keyboard(), parse_mode="HTML")
            await callback.answer()
            return
        if action == "groups":
            await callback.message.edit_text("<b>/tgov — escolha o grupo</b>", reply_markup=_groups_keyboard(), parse_mode="HTML")
            await callback.answer()
            return
        if action == "g" and len(parts) >= 3:
            palco = get_palco_internal_by_ref(grp_ref=parts[2])
            if not palco:
                await callback.answer("Grupo indisponível.", show_alert=True)
                return
            _state(user_id)["grp_ref"] = parts[2]
            _state(user_id)["grp_label"] = palco.get("titulo") or "Grupo"
            await callback.message.edit_text(_home_text(user_id), reply_markup=_home_keyboard(), parse_mode="HTML")
            await callback.answer()
            return
        if action == "ask" and len(parts) >= 3:
            kind = parts[2]
            palco = _selected_palco(user_id)
            if not palco:
                await callback.answer("Escolha um grupo antes.", show_alert=True)
                return
            if kind == "photo_remove":
                await callback.message.edit_text(
                    "<b>Confirmar remoção da foto do grupo?</b>\n\nAção owner-only e crítica.",
                    reply_markup=_keyboard([[InlineKeyboardButton(text="Remover foto", callback_data="tgov:yes:photo_remove")], [InlineKeyboardButton(text="Cancelar", callback_data="tgov:home")]]),
                    parse_mode="HTML",
                )
                await callback.answer()
                return
            prompts = {
                "title": "Envie o novo nome do grupo (1 a 128 caracteres).",
                "description": "Envie a nova descrição/bio do grupo (0 a 255 caracteres).",
                "post_copy": "Envie aqui a mensagem/post exatamente como deve ser publicado. O bot enviará uma cópia de prévia e pedirá confirmação.",
                "send_text": "Envie o texto que o bot publicará no grupo selecionado.",
                "send_photo": "Envie: URL_OU_FILE_ID | legenda opcional",
            }
            if kind not in prompts:
                await callback.answer("Ação indisponível.", show_alert=True)
                return
            _state(user_id)["awaiting"] = kind
            await callback.message.edit_text(prompts[kind], reply_markup=_keyboard([[InlineKeyboardButton(text="Cancelar", callback_data="tgov:home")]]))
            await callback.answer()
            return
        if action == "yes" and len(parts) >= 3 and parts[2] == "photo_remove":
            palco = _selected_palco(user_id)
            if not palco:
                await callback.answer("Escolha um grupo antes.", show_alert=True)
                return
            result = await executar_admin_critico(
                ajuste="grupo.foto.remover",
                palco=palco,
                ator_ref=_actor_ref(user_id),
                payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE, "ciente": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=engine,
            )
            await callback.message.edit_text("<b>/tgov concluído</b>\n\n" + _safe(result.get("resumo"), "Foto removida."), reply_markup=_home_keyboard(), parse_mode="HTML")
            await callback.answer("Concluído.")
            return
        if action == "post" and len(parts) >= 3:
            if parts[2] == "cancel":
                _state(user_id).pop("pending_post", None)
                _state(user_id).pop("awaiting", None)
                await callback.message.edit_text("Post cancelado.", reply_markup=_home_keyboard())
                await callback.answer("Cancelado.")
                return
            if parts[2] in {"send", "send_pin_silent"}:
                try:
                    result = await _publish_pending_post(
                        callback=callback,
                        user_id=user_id,
                        fixar_silencioso=(parts[2] == "send_pin_silent"),
                    )
                except Exception as exc:
                    logger.exception("TGOV_POST_COPY_PUBLISH_FAILED")
                    await callback.message.edit_text(
                        "<b>/tgov não concluído</b>\n\n" + _safe(mesa_error_public_detail(exc)),
                        reply_markup=_home_keyboard(),
                        parse_mode="HTML",
                    )
                    await callback.answer("Falhou.", show_alert=True)
                    return
                fix = result.get("fixacao")
                extra = ""
                if isinstance(fix, dict):
                    extra = "\nFixação: " + ("silenciosa concluída." if fix.get("ok") else _safe(fix.get("motivo"), "não concluída"))
                await callback.message.edit_text(
                    "<b>/tgov concluído</b>\n\nPost copiado para o grupo." + extra,
                    reply_markup=_home_keyboard(),
                    parse_mode="HTML",
                )
                await callback.answer("Publicado.")
                return
        if action == "tag_messages":
            palco = _selected_palco(user_id)
            if not palco:
                await callback.answer("Escolha um grupo antes.", show_alert=True)
                return
            await callback.message.edit_text("<b>/tgov · tag de membro</b>\n\nEscolha um autor recente capturado pelo X9.", reply_markup=_tag_messages_keyboard(user_id), parse_mode="HTML")
            await callback.answer()
            return
        if action == "tag_msg" and len(parts) >= 3:
            _state(user_id)["tag_msg_ref"] = parts[2]
            _state(user_id)["awaiting"] = "member_tag"
            await callback.message.edit_text("Envie a tag do membro (0 a 16 caracteres; envie '-' para remover).", reply_markup=_keyboard([[InlineKeyboardButton(text="Cancelar", callback_data="tgov:home")]]))
            await callback.answer()
            return
    except Exception:
        logger.exception("TGOV_CALLBACK_FAILED")
        await callback.answer("Ação owner não concluída.", show_alert=True)
        return
    await callback.answer("Ação indisponível.", show_alert=True)


@router.message(lambda m: bool(m.from_user and m.chat and m.chat.type == "private" and _STATE.get(int(m.from_user.id), {}).get("awaiting")))
async def tgov_waiting_message(message: Message) -> None:
    if not message.from_user:
        return
    user_id = int(message.from_user.id)
    if not _owner_allowed(user_id):
        return
    state = _state(user_id)
    awaiting = str(state.get("awaiting") or "")
    palco = _selected_palco(user_id)
    if not palco:
        await message.answer("Escolha um grupo primeiro com /tgov.")
        return
    text_value = str(message.text or "").strip()
    ator = upsert_context_operator(user=message.from_user, perfil="Owner")
    try:
        if awaiting == "post_copy" or awaiting == "post_copy_album":
            media_group_id = str(getattr(message, "media_group_id", "") or "")
            if awaiting == "post_copy_album":
                current_album = state.get("pending_post") if isinstance(state.get("pending_post"), dict) else {}
                if not media_group_id or str(current_album.get("media_group_id") or "") != media_group_id:
                    await message.answer("Álbum em coleta. Envie os demais itens do mesmo álbum ou use os botões para publicar/cancelar.", reply_markup=_post_confirm_keyboard())
                    return
            try:
                await message.bot.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    disable_notification=True,
                )
            except Exception as exc:
                logger.exception("TGOV_POST_COPY_PREVIEW_FAILED")
                await message.answer(
                    "Não consegui copiar essa mensagem. O Telegram não permite copiar alguns tipos de conteúdo, como mensagens de serviço, mídia paga, sorteios, vencedores de sorteios e certas enquetes.",
                    reply_markup=_home_keyboard(),
                )
                state.pop("awaiting", None)
                state.pop("pending_post", None)
                return
            resumo = (getattr(message, "text", None) or getattr(message, "caption", None) or _post_kind_label(message))[:160]
            if media_group_id:
                pending = state.get("pending_post") if isinstance(state.get("pending_post"), dict) else {}
                ids = _pending_message_ids(pending) if str(pending.get("media_group_id") or "") == media_group_id else []
                ids.append(int(message.message_id))
                ids = sorted(dict.fromkeys(ids))
                state["pending_post"] = {
                    "from_chat_id": int(message.chat.id),
                    "message_id": int(ids[0]),
                    "message_ids": ids,
                    "media_group_id": media_group_id,
                    "tipo": "álbum",
                    "resumo": resumo or "Álbum copiado",
                }
                state["awaiting"] = "post_copy_album"
                await message.answer(
                    f"Prévia do item copiada acima. Álbum em coleta: {_album_item_count_text(len(ids))}. Quando todos os itens chegarem, confirme a publicação.",
                    reply_markup=_post_confirm_keyboard(),
                )
                return
            state["pending_post"] = {
                "from_chat_id": int(message.chat.id),
                "message_id": int(message.message_id),
                "message_ids": [int(message.message_id)],
                "tipo": _post_kind_label(message),
                "resumo": resumo,
            }
            state.pop("awaiting", None)
            await message.answer(
                "Prévia copiada acima. Confirma publicar esta cópia no grupo selecionado?",
                reply_markup=_post_confirm_keyboard(),
            )
            return
        if awaiting == "title":
            title = text_value[:128].strip()
            if not title:
                await message.answer("Nome vazio. Envie um nome válido.")
                return
            result = await executar_admin_critico(
                ajuste="grupo.titulo",
                palco=palco,
                ator_ref=_actor_ref(user_id),
                payload={"titulo": title, "confirmacao": MAESTRO_CONFIRMATION_PHRASE, "ciente": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=engine,
            )
        elif awaiting == "description":
            result = await executar_admin_critico(
                ajuste="grupo.descricao",
                palco=palco,
                ator_ref=_actor_ref(user_id),
                payload={"descricao": text_value[:255], "confirmacao": MAESTRO_CONFIRMATION_PHRASE, "ciente": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=engine,
            )
        elif awaiting == "send_text":
            if not text_value:
                await message.answer("Texto vazio.")
                return
            result = await executar_ajuste(
                ajuste="mensagens.enviar",
                palco=palco,
                ator_ref=str(ator["usr_ref"]),
                payload={"texto": text_value[:3900], "sem_notificacao": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        elif awaiting == "send_photo":
            parts = [part.strip() for part in text_value.split("|", 1)]
            photo = parts[0] if parts else ""
            caption = parts[1] if len(parts) > 1 else ""
            if not photo:
                await message.answer("Informe URL HTTPS ou file_id da foto.")
                return
            result = await executar_ajuste(
                ajuste="mensagens.enviar_foto",
                palco=palco,
                ator_ref=str(ator["usr_ref"]),
                payload={"foto": photo, "legenda": caption[:1024], "sem_notificacao": True},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        elif awaiting == "member_tag":
            from app.fsm_tigrao.context import get_message_by_ref
            msg = get_message_by_ref(msg_ref=str(state.get("tag_msg_ref") or ""))
            if not msg or not msg.get("autor_ref"):
                await message.answer("Autor capturado indisponível. Reabra /tgov e escolha uma mensagem recente.")
                return
            tag = "" if text_value == "-" else text_value[:16]
            result = await executar_ajuste_avancado(
                ajuste="membros.tag.definir",
                palco=palco,
                ator_ref=_actor_ref(user_id),
                payload={"alvo_ref": msg["autor_ref"], "tag": tag},
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        else:
            await message.answer("Entrada owner expirada.")
            state.pop("awaiting", None)
            return
        state.pop("awaiting", None)
        await message.answer("<b>/tgov concluído</b>\n\n" + _safe(result.get("resumo") or "Ação executada."), reply_markup=_home_keyboard(), parse_mode="HTML")
    except Exception as exc:
        logger.exception("TGOV_WAITING_FAILED awaiting=%s", awaiting)
        detail = avancado_error_public_detail(exc) if awaiting == "member_tag" else mesa_error_public_detail(exc)
        await message.answer("<b>/tgov não concluído</b>\n\n" + _safe(detail), reply_markup=_home_keyboard(), parse_mode="HTML")
