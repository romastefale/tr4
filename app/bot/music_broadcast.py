"""Broadcast musical TR4 — owner /tbrd e Web App governante."""
from __future__ import annotations

import html
import logging
import random
import time
import uuid
from typing import Any, Iterable

from aiogram import Bot, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.bot.music_broadcast_core import (
    BroadcastTarget,
    add_manual_music_catalog_item,
    add_music_broadcast_block,
    build_music_broadcast_caption,
    choose_manual_catalog_track,
    create_music_broadcast_schedule,
    delete_music_broadcast_schedule,
    due_music_broadcast_schedules,
    is_music_broadcast_blocked,
    list_manual_music_catalog,
    list_music_broadcast_blocks,
    list_music_broadcast_schedules,
    mark_manual_catalog_used,
    mark_music_broadcast_schedule_run,
    record_music_broadcast_run,
    remove_manual_music_catalog_item,
    remove_music_broadcast_block,
    selection_from_arg,
    set_music_broadcast_schedule_paused,
    summarize_run,
    targets_from_music_groups,
    track_identity,
)
from app.bot.music_groups import list_groups
from app.config import settings
from app.db.database import engine as default_engine
from app.services.music import music_service
from app.services.lastfm import lastfm_service
from app.services.spotify import spotify_service
from app.services.spotify_canvas import spotify_canvas_service

logger = logging.getLogger(__name__)
router = Router(name="music_broadcast")


async def get_current_lastfm_track(user_id: int) -> dict[str, Any] | None:
    """Return only the track that is currently playing on Last.fm.

    Manual /tbrd and governante Web App broadcast must not fall back to
    last played tracks or Spotify history. If Last.fm does not report
    ``nowplaying=true``, the caller must not send anything.
    """
    try:
        track = await lastfm_service.get_current_or_last_played(int(user_id))
    except Exception:
        logger.debug("MUSIC_BROADCAST_LASTFM_CURRENT_FAILED user=%s", user_id, exc_info=True)
        return None
    if not track:
        return None
    if str(track.get("source") or "") != "lastfm_current":
        return None
    info = track_identity(track)
    if not (info["track_name"] and info["artist"]):
        return None
    return track


def _record_music_broadcast_failure(
    *,
    actor_user_id: int,
    actor_kind: str,
    targets: Iterable[BroadcastTarget],
    reason: str,
    db_engine: Engine = default_engine,
) -> dict[str, Any]:
    targets_list = list(targets)
    run_ref = f"mbc_{uuid.uuid4().hex[:16]}"
    results = [
        {"chat_id": int(target.chat_id), "status": "falhou", "reason": str(reason or "falha")[:180]}
        for target in targets_list
    ]
    placeholder_track = {"track_name": "indisponível", "artist": "indisponível", "source": "scheduler_failure"}
    record_music_broadcast_run(
        run_ref=run_ref,
        actor_user_id=int(actor_user_id or 0),
        actor_kind=actor_kind,
        track=placeholder_track,
        results=results,
        db_engine=db_engine,
    )
    return summarize_run(run_ref, results)

_PENDING_TTL_SECONDS = 300
_PENDING_MAX = 50
_PENDING: dict[str, dict[str, Any]] = {}


async def _resolve_canvas_track_id(track: dict[str, Any]) -> str:
    info = track_identity(track)
    track_id = info["track_id"]
    if not track_id:
        return ""
    if not track_id.startswith("lfm:"):
        return track_id
    if not (info["artist"] and info["track_name"]):
        return ""
    try:
        match = await spotify_service.search_track(info["artist"], info["track_name"])
        return str((match or {}).get("id") or "").strip()
    except Exception:
        logger.debug("MUSIC_BROADCAST_CANVAS_RESOLVE_FAILED", exc_info=True)
        return ""


async def _try_canvas_bytes(track: dict[str, Any]) -> tuple[str, bytes | None]:
    canvas_track_id = await _resolve_canvas_track_id(track)
    if not canvas_track_id:
        return "", None
    try:
        canvas_url = await spotify_canvas_service.get_canvas_url(canvas_track_id)
        if not canvas_url:
            return canvas_track_id, None
        data = await spotify_canvas_service.download_canvas_bytes(canvas_url)
        return canvas_track_id, data or None
    except Exception:
        logger.debug("MUSIC_BROADCAST_CANVAS_BYTES_FAILED", exc_info=True)
        return canvas_track_id, None


async def send_track_card_to_chat(
    bot: Bot,
    *,
    chat_id: int,
    listener_name: str,
    track: dict[str, Any],
    actor_label: str,
    silent: bool = False,
    fixar: bool = False,
) -> dict[str, Any]:
    info = track_identity(track)
    caption = build_music_broadcast_caption(track, listener_name=listener_name, actor_label=actor_label)
    canvas_track_id, canvas_bytes = await _try_canvas_bytes(track)
    sent = None
    if canvas_bytes:
        sent = await bot.send_video(
            chat_id=chat_id,
            video=BufferedInputFile(canvas_bytes, filename=f"broadcast-{canvas_track_id or 'track'}.mp4"),
            caption=caption,
            parse_mode="HTML",
            disable_notification=silent,
        )
    elif info["cover"]:
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=info["cover"],
            caption=caption,
            parse_mode="HTML",
            disable_notification=silent,
        )
    else:
        raise RuntimeError("sem card/canvas para transmitir")
    if fixar:
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=sent.message_id, disable_notification=True)
        except Exception:
            logger.debug("MUSIC_BROADCAST_PIN_FAILED chat=%s msg=%s", chat_id, sent.message_id, exc_info=True)
    return {"status": "enviado", "message_id": int(sent.message_id), "used_canvas": bool(canvas_bytes), "used_cover": not bool(canvas_bytes)}


async def execute_music_broadcast(
    bot: Bot,
    *,
    actor_user_id: int,
    actor_kind: str,
    track: dict[str, Any],
    targets: Iterable[BroadcastTarget],
    silent: bool = False,
    fixar: bool = False,
    db_engine: Engine = default_engine,
) -> dict[str, Any]:
    targets_list = list(targets)
    run_ref = f"mbc_{uuid.uuid4().hex[:16]}"
    blocked, reason = is_music_broadcast_blocked(track, db_engine=db_engine)
    results: list[dict[str, Any]] = []
    if blocked:
        for target in targets_list:
            results.append({"chat_id": target.chat_id, "status": "bloqueado", "reason": reason})
        record_music_broadcast_run(run_ref=run_ref, actor_user_id=actor_user_id, actor_kind=actor_kind, track=track, results=results, db_engine=db_engine)
        return summarize_run(run_ref, results, blocked_reason=reason)
    for target in targets_list[:25]:
        try:
            sent = await send_track_card_to_chat(bot, chat_id=target.chat_id, listener_name=target.title, track=track, actor_label="TR4", silent=silent, fixar=fixar)
            results.append({"chat_id": target.chat_id, "status": "enviado", "message_id": sent.get("message_id")})
        except Exception as exc:
            logger.debug("MUSIC_BROADCAST_TARGET_FAILED chat=%s", target.chat_id, exc_info=True)
            results.append({"chat_id": target.chat_id, "status": "falhou", "reason": str(exc)[:180]})
    record_music_broadcast_run(run_ref=run_ref, actor_user_id=actor_user_id, actor_kind=actor_kind, track=track, results=results, db_engine=db_engine)
    if any(item.get("status") == "enviado" for item in results) and str(track.get("source") or "") == "manual_catalog":
        mark_manual_catalog_used(catalog_ref=str(track.get("catalog_ref") or ""), db_engine=db_engine)
    return summarize_run(run_ref, results)

def _registered_music_user_ids(*, db_engine: Engine = default_engine, preferred_user_id: int | None = None, limit: int = 40) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    if preferred_user_id:
        seen.add(int(preferred_user_id)); out.append(int(preferred_user_id))
    with db_engine.begin() as conn:
        for table in ("lastfm_profiles", "spotify_tokens"):
            try:
                rows = conn.execute(text(f"SELECT DISTINCT user_id FROM {table} WHERE user_id IS NOT NULL LIMIT :limit"), {"limit": int(limit)}).mappings().all()
            except Exception:
                continue
            for row in rows:
                try:
                    uid = int(row["user_id"])
                except Exception:
                    continue
                if uid > 0 and uid not in seen:
                    seen.add(uid); out.append(uid)
    head = out[:1]
    tail = out[1:]
    random.shuffle(tail)
    return (head + tail)[: max(1, int(limit))]


async def select_automatic_broadcast_track(*, preferred_user_id: int | None = None, db_engine: Engine = default_engine) -> dict[str, Any] | None:
    """Pick a usable automatic track from manual catalog and known profiles.

    Etapa 13: the owner manual catalog is now the first-class source for
    automatic broadcast. The picker avoids recent repetitions when possible,
    still samples Last.fm/Spotify profiles as fallback, and never returns a
    text-only item without cover/canvas/card data.
    """
    catalog_track = choose_manual_catalog_track(db_engine=db_engine)
    if catalog_track:
        return catalog_track
    recent_candidates: list[dict[str, Any]] = []
    for uid in _registered_music_user_ids(db_engine=db_engine, preferred_user_id=preferred_user_id, limit=40):
        try:
            track = await music_service.get_current_or_last_played(int(uid))
        except Exception:
            logger.debug("MUSIC_BROADCAST_AUTO_TRACK_LOOKUP_FAILED user=%s", uid, exc_info=True)
            continue
        if not track:
            continue
        blocked, _reason = is_music_broadcast_blocked(track, db_engine=db_engine)
        if blocked:
            continue
        info = track_identity(track)
        if info["track_name"] and info["artist"] and (info["cover"] or info["track_id"]):
            track.setdefault("source_user_id", uid)
            track.setdefault("source", track.get("source") or "known_profile")
            recent_candidates.append(track)
    if not recent_candidates:
        return None
    random.shuffle(recent_candidates)
    return recent_candidates[0]


async def run_due_music_broadcast_schedules(bot: Bot, *, db_engine: Engine = default_engine, limit: int = 10) -> dict[str, Any]:
    processed: list[dict[str, Any]] = []
    for schedule in due_music_broadcast_schedules(db_engine=db_engine)[: max(1, int(limit))]:
        target = BroadcastTarget(chat_id=int(schedule["chat_id"]), title=str(schedule.get("title") or "Grupo"))
        due_slot = str(schedule.get("due_slot") or "")
        track = await select_automatic_broadcast_track(preferred_user_id=schedule.get("created_by"), db_engine=db_engine)
        if not track:
            result = _record_music_broadcast_failure(
                actor_user_id=int(schedule.get("created_by") or 0),
                actor_kind="owner_auto",
                targets=[target],
                reason="sem música disponível",
                db_engine=db_engine,
            )
            mark_music_broadcast_schedule_run(schedule_ref=str(schedule["schedule_ref"]), due_slot=due_slot, sent=False, db_engine=db_engine)
            processed.append({"schedule_ref": schedule["schedule_ref"], "status": "falhou", "reason": "sem música disponível", "result": result})
            continue
        result = await execute_music_broadcast(
            bot,
            actor_user_id=int(schedule.get("created_by") or 0),
            actor_kind="owner_auto",
            track=track,
            targets=[target],
            silent=bool(schedule.get("silent")),
            fixar=bool(schedule.get("fixar")),
            db_engine=db_engine,
        )
        sent = int(result.get("enviados") or 0) > 0
        mark_music_broadcast_schedule_run(schedule_ref=str(schedule["schedule_ref"]), due_slot=due_slot, sent=sent, db_engine=db_engine)
        processed.append({"schedule_ref": schedule["schedule_ref"], "status": "enviado" if sent else "falhou", "result": result})
    return {"ok": True, "processed": processed, "count": len(processed)}



def _purge_pending() -> None:
    now = time.monotonic()
    stale = [key for key, item in _PENDING.items() if now - float(item.get("created", now)) > _PENDING_TTL_SECONDS]
    for key in stale:
        _PENDING.pop(key, None)
    if len(_PENDING) > _PENDING_MAX:
        for key in list(_PENDING)[: len(_PENDING) - _PENDING_MAX]:
            _PENDING.pop(key, None)


def _is_owner(user_id: int) -> bool:
    return int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET


def _render_preview(track: dict[str, Any], groups: list[BroadcastTarget], pending_ref: str) -> tuple[str, InlineKeyboardMarkup]:
    info = track_identity(track)
    group_lines = [f"{idx}. {html.escape(target.title)}" for idx, target in enumerate(groups[:10], start=1)]
    text_value = (
        "<b>/tbrd — prévia owner</b>\n"
        "Envio manual da música atual. Escolha por botão ou envie /tbrd all ou /tbrd 1,3.\n\n"
        f"Música: <b>{html.escape(info['track_name'] or 'indisponível')}</b> — <i>{html.escape(info['artist'] or 'indisponível')}</i>\n"
        f"Grupos conhecidos: {len(groups)}\n"
        + ("\n".join(group_lines) if group_lines else "Nenhum grupo conhecido.")
    )
    buttons = [[InlineKeyboardButton(text="Enviar todos", callback_data=f"mbc:{pending_ref}:all")]]
    row: list[InlineKeyboardButton] = []
    for idx, _target in enumerate(groups[:3], start=1):
        row.append(InlineKeyboardButton(text=f"Grupo {idx}", callback_data=f"mbc:{pending_ref}:{idx}"))
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Cancelar", callback_data=f"mbc:{pending_ref}:cancel")])
    return text_value[:3900], InlineKeyboardMarkup(inline_keyboard=buttons)


def _render_blocks_text() -> str:
    rows = list_music_broadcast_blocks()
    if not rows:
        return "<b>Bloqueios musicais</b>\nNenhum artista/faixa bloqueado."
    lines = ["<b>Bloqueios musicais</b>"]
    for row in rows[:25]:
        lines.append(f"{row['id']}. {html.escape(row['block_type'])}: {html.escape(row['raw_value'])}")
    return "\n".join(lines)[:3900]



def _render_catalog_text() -> str:
    rows = list_manual_music_catalog()
    lines = ["<b>Catálogo manual do owner</b>"]
    if not rows:
        lines.append("Nenhuma música cadastrada.")
    for row in rows[:25]:
        status = "ativa" if row.get("enabled") else "desativada"
        lines.append(f"• {html.escape(row['catalog_ref'])} · {html.escape(row.get('artist') or '')} — {html.escape(row.get('track_name') or '')} · {status}")
    lines.extend([
        "",
        "Adicionar: /tbrd catalog add Artista - Música | https://capa | https://spotify",
        "Remover: /tbrd catalog delete mbcat_xxx",
    ])
    return "\n".join(lines)[:3900]


def _parse_catalog_add(raw: str) -> dict[str, str]:
    # Format: Artista - Música | capa | spotify
    parts = [part.strip() for part in str(raw or "").split("|")]
    head = parts[0] if parts else ""
    if " - " in head:
        artist, track = head.split(" - ", 1)
    elif " – " in head:
        artist, track = head.split(" – ", 1)
    else:
        raise ValueError("use Artista - Música")
    return {
        "artist": artist.strip(),
        "track_name": track.strip(),
        "cover_url": parts[1].strip() if len(parts) > 1 else "",
        "spotify_url": parts[2].strip() if len(parts) > 2 else "",
    }

def _render_schedules_text() -> str:
    rows = list_music_broadcast_schedules()
    if not rows:
        return "<b>Broadcast automático</b>\nNenhum agendamento configurado."
    lines = ["<b>Broadcast automático</b>"]
    for row in rows[:25]:
        status = "pausado" if row.get("paused") else "ativo"
        lines.append(f"• {html.escape(row['schedule_ref'])} · {html.escape(row.get('title') or 'Grupo')} · {', '.join(row.get('times') or [])} · {status}")
    return "\n".join(lines)[:3900]


async def _handle_broadcast_owner_subcommand(message: Message, user_id: int, args: str) -> bool:
    lower = args.strip().lower()
    if lower == "blocks":
        await message.answer(_render_blocks_text(), parse_mode="HTML")
        return True
    if lower == "catalog":
        await message.answer(_render_catalog_text(), parse_mode="HTML", disable_web_page_preview=True)
        return True
    if lower.startswith("catalog add "):
        try:
            payload = _parse_catalog_add(args[len("catalog add "):])
            item = add_manual_music_catalog_item(created_by=user_id, **payload)
            await message.answer(f"Catálogo manual salvo: {html.escape(item['catalog_ref'])}", parse_mode="HTML")
        except Exception:
            await message.answer("Não consegui salvar. Use: /tbrd catalog add Artista - Música | https://capa | https://spotify")
        return True
    if lower.startswith("catalog delete "):
        ref = args[len("catalog delete "):].strip()
        ok = remove_manual_music_catalog_item(catalog_ref=ref)
        await message.answer("Música removida do catálogo." if ok else "Música não encontrada no catálogo.")
        return True
    if lower.startswith("block artist ") or lower.startswith("block track "):
        parts = args.split(maxsplit=2)
        block_type = parts[1]
        value = parts[2].strip() if len(parts) > 2 else ""
        if not value:
            await message.answer("Informe o artista ou faixa para bloquear.")
            return True
        add_music_broadcast_block(block_type=block_type, value=value, created_by=user_id)
        await message.answer(f"Bloqueio salvo: {html.escape(block_type)} · {html.escape(value)}", parse_mode="HTML")
        return True
    if lower.startswith("unblock "):
        try:
            block_id = int(args.split(maxsplit=1)[1])
        except Exception:
            await message.answer("Use /tbrd unblock ID.")
            return True
        ok = remove_music_broadcast_block(block_id=block_id)
        await message.answer("Bloqueio removido." if ok else "Bloqueio não encontrado.")
        return True
    if lower == "schedules":
        await message.answer(_render_schedules_text(), parse_mode="HTML")
        return True
    if lower.startswith("pause ") or lower.startswith("resume "):
        cmd, ref = args.split(maxsplit=1)
        ok = set_music_broadcast_schedule_paused(schedule_ref=ref.strip(), paused=(cmd.lower() == "pause"))
        await message.answer("Agendamento atualizado." if ok else "Agendamento não encontrado.")
        return True
    if lower.startswith("delete "):
        ref = args.split(maxsplit=1)[1].strip()
        ok = delete_music_broadcast_schedule(schedule_ref=ref)
        await message.answer("Agendamento removido." if ok else "Agendamento não encontrado.")
        return True
    if lower.startswith("schedule "):
        # /tbrd schedule 1 09:00,18:00 [fixar] [silent] confirmar
        parts = args.split()
        if len(parts) < 3:
            await message.answer("Use /tbrd schedule 1 09:00,18:00 confirmar")
            return True
        groups = targets_from_music_groups(list_groups(limit=25))
        targets = selection_from_arg(parts[1], groups)
        if not targets:
            await message.answer("Grupo inválido. Gere /tbrd para ver a numeração ou use all.")
            return True
        flags = {part.lower() for part in parts[3:]}
        preview_track = await select_automatic_broadcast_track(preferred_user_id=user_id)
        if not preview_track:
            await message.answer("Não há música com card/capa disponível para prévia do agendamento automático.")
            return True
        info = track_identity(preview_track)
        preview_text = (
            "<b>Prévia do agendamento automático</b>\n"
            f"Música candidata: <b>{html.escape(info['track_name'])}</b> — <i>{html.escape(info['artist'])}</i>\n"
            f"Grupos: {len(targets)} · horários: {html.escape(parts[2])}\n\n"
            "Para criar de fato, repita o comando adicionando <code>confirmar</code>."
        )
        if "confirmar" not in flags and "confirm" not in flags:
            await message.answer(preview_text, parse_mode="HTML")
            return True
        created = []
        for target in targets:
            created.append(create_music_broadcast_schedule(
                chat_id=target.chat_id,
                title=target.title,
                times=parts[2],
                times_per_day=len(parts[2].split(",")),
                created_by=user_id,
                fixar="fixar" in flags,
                silent="silent" in flags or "silencioso" in flags,
                preview_confirmed=True,
            ))
        await message.answer(f"Agendamento(s) criado(s): {len(created)}.")
        return True
    return False


@router.message(Command("tbrd", "broadcast"))
async def broadcast_command(message: Message) -> None:
    if not message.from_user:
        return
    if message.chat.type != "private":
        await message.answer("Use /tbrd no privado do owner.")
        return
    user_id = int(message.from_user.id)
    if not _is_owner(user_id):
        await message.answer("Acesso indisponível.")
        return
    _purge_pending()
    args = ""
    try:
        args = (message.text or "").split(maxsplit=1)[1].strip()
    except Exception:
        args = ""
    if args and await _handle_broadcast_owner_subcommand(message, user_id, args):
        return
    if args:
        pending = next((item for item in reversed(list(_PENDING.values())) if int(item.get("user_id") or 0) == user_id), None)
        if not pending:
            await message.answer("Gere a prévia primeiro com /tbrd.")
            return
        targets = selection_from_arg(args, pending["groups"])
        if not targets:
            await message.answer("Seleção vazia. Use /tbrd all ou números como /tbrd 1,3.")
            return
        result = await execute_music_broadcast(message.bot, actor_user_id=user_id, actor_kind="owner", track=pending["track"], targets=targets, silent=bool(pending.get("silent", False)), fixar=bool(pending.get("fixar", False)))
        await message.answer(html.escape(str(result.get("resumo") or "Broadcast concluído.")), parse_mode="HTML")
        return
    track = await get_current_lastfm_track(user_id)
    if not track:
        await message.answer("Nada está tocando agora no Last.fm. O /tbrd manual não usa última música nem fallback Spotify.")
        return
    blocked, reason = is_music_broadcast_blocked(track)
    if blocked:
        await message.answer(f"Broadcast bloqueado: {html.escape(reason)}", parse_mode="HTML")
        return
    groups = targets_from_music_groups(list_groups(limit=25))
    if not groups:
        await message.answer("Nenhum grupo conhecido para broadcast musical.")
        return
    pending_ref = uuid.uuid4().hex[:10]
    _PENDING[pending_ref] = {"user_id": user_id, "track": track, "groups": groups, "created": time.monotonic(), "silent": False, "fixar": False}
    text_value, keyboard = _render_preview(track, groups, pending_ref)
    await message.answer(text_value, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


@router.callback_query(lambda query: bool(query.data and str(query.data).startswith("mbc:")))
async def broadcast_callback(query: CallbackQuery) -> None:
    if not query.from_user:
        return
    user_id = int(query.from_user.id)
    if not _is_owner(user_id):
        await query.answer("Acesso indisponível.", show_alert=True)
        return
    parts = str(query.data or "").split(":", 2)
    if len(parts) != 3:
        await query.answer("Callback inválido.", show_alert=True)
        return
    _prefix, pending_ref, choice = parts
    pending = _PENDING.get(pending_ref)
    if not pending or int(pending.get("user_id") or 0) != user_id:
        await query.answer("Prévia expirada.", show_alert=True)
        return
    if choice == "cancel":
        _PENDING.pop(pending_ref, None)
        await query.answer("Cancelado.")
        if query.message:
            await query.message.edit_reply_markup(reply_markup=None)
        return
    targets = selection_from_arg(choice, pending["groups"])
    if not targets:
        await query.answer("Seleção vazia.", show_alert=True)
        return
    await query.answer("Enviando broadcast musical.")
    result = await execute_music_broadcast(query.bot, actor_user_id=user_id, actor_kind="owner", track=pending["track"], targets=targets, silent=bool(pending.get("silent", False)), fixar=bool(pending.get("fixar", False)))
    if query.message:
        await query.message.answer(html.escape(str(result.get("resumo") or "Broadcast concluído.")), parse_mode="HTML")


async def execute_governante_current_music_broadcast(
    *,
    actor_user_id: int,
    chat_id: int,
    chat_title: str,
    bot_token: str,
    db_engine: Engine = default_engine,
) -> dict[str, Any]:
    track = await get_current_lastfm_track(int(actor_user_id))
    if not track:
        return {"ok": False, "detail": "Nada está tocando agora no Last.fm."}
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        return await execute_music_broadcast(
            bot,
            actor_user_id=int(actor_user_id),
            actor_kind="governante",
            track=track,
            targets=[BroadcastTarget(chat_id=int(chat_id), title=chat_title or "Grupo")],
            silent=False,
            fixar=False,
            db_engine=db_engine,
        )
    finally:
        await bot.session.close()
