"""/tnow — mosaico musical com escopo explícito e cache persistente.

Regras consolidadas:
- Grupo/supergrupo: mostra somente usuários cadastrados que ainda são membros
  daquele chat. Este fluxo é livre para membros do grupo.
- DM/privado sem grupo: é matriz universal e só pode ser executada pelo dono
  do código. Usuário comum nunca recebe mosaico universal.
- A captura usa somente dado musical real: tocando agora, última faixa recente
  ou último dado real salvo em `tnow_recent_tracks` dentro de até 2 horas.
- O nome visual do card prioriza o username Last.fm cadastrado; Telegram é
  apenas fallback.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Chat, Message
from sqlalchemy import select

from app.config.settings import SPOTIFY_MAX_CONCURRENT_REQUESTS, is_code_owner
from app.db.database import SessionLocal
from app.models.lastfm_profile import LastfmProfile
from app.models.spotify_token import SpotifyToken
from app.services.cover_cache import cover_cache_service
from app.services.lastfm import lastfm_service
from app.services.spotify import spotify_service
from app.services.tnow_activity_cache import (
    TNOW_RECENT_120_SECONDS,
    TNOW_RECENT_15_SECONDS,
    TNOW_RECENT_30_SECONDS,
    TNOW_RECENT_45_SECONDS,
    TNOW_STATUS_PRIORITY,
    TnowActivityHit,
    classify_recent_track,
    tnow_activity_cache_service,
)
from app.services.tnow_card import TnowEntry, render_tnow_card
from app.services.tnow_privacy import TPV_DEFAULT_LABEL, normalize_tpv_mode, tnow_privacy_service

logger = logging.getLogger(__name__)
router = Router(name="tnow")

# Limite duro para evitar requests excessivos. A seleção final usa layouts
# completos com no máximo 5x5 = 25 tiles.
MAX_USERS = 60
MAX_TILES = 25
COVER_FETCH_TIMEOUT = 8.0
TNOW_SNAPSHOT_TTL_SECONDS = 75.0
TNOW_GATHER_CONCURRENCY = max(1, min(20, int(SPOTIFY_MAX_CONCURRENT_REQUESTS or 10)))

TNOW_RECENT_YELLOW_MINUTES = 15
TNOW_RECENT_ORANGE_MINUTES = 30
TNOW_RECENT_RED_MINUTES = 45
TNOW_RECENT_GRAY_MINUTES = 120
_TNOW_ACCEPTED_TRACK_SOURCES = {"spotify_current", "spotify_last", "lastfm_current", "lastfm_last"}

# Ordem pedida: tenta completar 5x5, depois 5x4, 4x4, 3x4 e assim por diante.
# Tupla = (linhas, colunas). O card usa o número de colunas correspondente.
_TNOW_GRID_LAYOUTS: tuple[tuple[int, int], ...] = (
    (5, 5),
    (5, 4),
    (4, 4),
    (3, 4),
    (3, 3),
    (2, 4),
    (2, 3),
    (2, 2),
    (1, 3),
    (1, 2),
    (1, 1),
)


@dataclass(frozen=True)
class _TnowSnapshot:
    created_at: float
    entries: tuple[TnowEntry, ...]


_TNOW_SNAPSHOTS: dict[str, _TnowSnapshot] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_played_at(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        logger.debug("TNOW_PLAYED_AT_PARSE_FAILED | value=%s", raw, exc_info=True)
        return None


def _classify_tnow_track(track: dict[str, Any] | None, *, source_tag: str, now: datetime) -> dict[str, Any] | None:
    """Classifica uma resposta crua de Spotify/Last.fm.

    A faixa expirada (>2h) volta marcada como `expired` para permitir que a
    tabela persistente também expire o registro anterior daquele usuário.
    """
    if not track:
        return None

    source = str(track.get("source") or "")
    if source and source not in _TNOW_ACCEPTED_TRACK_SOURCES:
        return None
    is_live = source in {"spotify_current", "lastfm_current"}
    if source == "spotify_current" and not bool(track.get("is_playing", True)):
        is_live = False

    out = dict(track)
    out["_source_tag"] = source_tag
    out["_tnow_is_live"] = is_live

    played_at = _parse_played_at(out.get("played_at"))
    observed_at = now
    decision = classify_recent_track(
        is_live=is_live,
        played_at=played_at,
        observed_at=observed_at,
        fetched_at=now,
        now=now,
    )
    if decision is None:
        return None

    age_seconds = max(0.0, decision.age_seconds)
    out["_tnow_status"] = decision.status
    out["_tnow_age_minutes"] = int(age_seconds // 60)
    out["_tnow_age_seconds"] = int(age_seconds)
    out["_tnow_observed_at_iso"] = observed_at.isoformat()
    if played_at is not None:
        out["_tnow_played_at_iso"] = played_at.isoformat()
    return out


def _candidate_sort_key(track: dict[str, Any]) -> tuple[int, int, int]:
    status = str(track.get("_tnow_status") or "expired")
    source = str(track.get("_source_tag") or "")
    age = int(track.get("_tnow_age_seconds") or 0)
    return (
        TNOW_STATUS_PRIORITY.get(status, 99),
        0 if source == "spotify" else 1,
        age,
    )


def _entry_sort_key(entry: TnowEntry) -> tuple[int, int, str]:
    return (
        TNOW_STATUS_PRIORITY.get(entry.status, 99),
        int((entry.age_minutes or 0) * 60),
        entry.display_name.lower(),
    )


def _activity_sort_key(activity: TnowActivityHit) -> tuple[int, int, str]:
    return (
        TNOW_STATUS_PRIORITY.get(activity.status, 99),
        int(activity.raw_age_seconds or 0),
        (activity.lastfm_username or "").lower(),
    )


def _choose_grid_layout(n: int) -> tuple[int, int, int]:
    """Retorna (linhas, colunas, slots) da maior grade completa possível."""
    if n <= 0:
        return 0, 0, 0
    for rows, columns in _TNOW_GRID_LAYOUTS:
        slots = rows * columns
        if n >= slots:
            return rows, columns, min(slots, MAX_TILES)
    return 1, 1, 1


def _grid_slots(n: int) -> int:
    """Compatibilidade estática: slots da grade completa escolhida."""
    return _choose_grid_layout(n)[2]


def _scope_kind(chat: Chat | None) -> str:
    if chat is not None and chat.type in _GROUP_TYPES:
        return "group"
    return "universal"


def _snapshot_key(chat: Chat | None) -> str:
    if chat is not None and chat.type in _GROUP_TYPES:
        return f"tnow:group:{int(chat.id)}"
    return "tnow:universal"


def _get_snapshot(key: str) -> list[TnowEntry] | None:
    item = _TNOW_SNAPSHOTS.get(key)
    if item is None:
        return None
    age = time.monotonic() - item.created_at
    if age > TNOW_SNAPSHOT_TTL_SECONDS:
        _TNOW_SNAPSHOTS.pop(key, None)
        return None
    logger.info(
        "TNOW_SNAPSHOT_HIT | scope=%s | age=%.1f | selected=%s",
        key,
        age,
        len(item.entries),
    )
    return list(item.entries)


def _put_snapshot(key: str, entries: list[TnowEntry]) -> None:
    _TNOW_SNAPSHOTS[key] = _TnowSnapshot(created_at=time.monotonic(), entries=tuple(entries))
    if len(_TNOW_SNAPSHOTS) > 100:
        now = time.monotonic()
        for stale_key, snapshot in list(_TNOW_SNAPSHOTS.items()):
            if now - snapshot.created_at > TNOW_SNAPSHOT_TTL_SECONDS:
                _TNOW_SNAPSHOTS.pop(stale_key, None)


def _registered_user_ids() -> list[int]:
    with SessionLocal() as db:
        spotify_ids = db.execute(select(SpotifyToken.user_id)).scalars().all()
        lastfm_ids = db.execute(select(LastfmProfile.user_id)).scalars().all()
    seen: set[int] = set()
    out: list[int] = []
    for uid in (*spotify_ids, *lastfm_ids):
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out[:MAX_USERS]


async def _fetch_cover(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=COVER_FETCH_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.content
    except Exception:
        logger.debug("TNOW_COVER_FETCH_FAILED | url=%s", url, exc_info=True)
    return None


async def _resolve_now_playing(user_id: int, *, now: datetime) -> dict[str, Any] | None:
    """Resolve a melhor faixa real agora, sem depender do cache persistente."""
    candidates: list[dict[str, Any]] = []

    try:
        sp = await spotify_service.get_current_or_last_played(user_id)
    except Exception:
        logger.exception("TNOW_SPOTIFY_PROBE_FAILED | user_id=%s", user_id)
        sp = None
    sp_candidate = _classify_tnow_track(sp, source_tag="spotify", now=now)
    if sp_candidate:
        if sp_candidate.get("_tnow_status") == "live":
            return sp_candidate
        candidates.append(sp_candidate)

    try:
        lf = await lastfm_service.get_current_or_last_played(user_id)
    except Exception:
        logger.exception("TNOW_LASTFM_PROBE_FAILED | user_id=%s", user_id)
        lf = None
    lf_candidate = _classify_tnow_track(lf, source_tag="lastfm", now=now)
    if lf_candidate:
        candidates.append(lf_candidate)

    if not candidates:
        return None

    candidates.sort(key=_candidate_sort_key)
    return candidates[0]


def _lastfm_display_name(user_id: int) -> str | None:
    """Fallback visual for imported users whose Telegram profile is not reachable."""
    try:
        with SessionLocal() as db:
            username = db.execute(
                select(LastfmProfile.username).where(LastfmProfile.user_id == user_id)
            ).scalar_one_or_none()
    except Exception:
        logger.debug("TNOW_LASTFM_NAME_LOOKUP_FAILED | user_id=%s", user_id, exc_info=True)
        return None
    username = str(username or "").strip()
    return username or None


async def _display_name(bot: Any, user_id: int, lastfm_username: str | None = None, *, surface: str = "tnow") -> str:
    # /tpv é owner-only e só mascara o nome renderizado. A busca musical segue
    # usando Last.fm/Spotify e a música continua aparecendo normalmente.
    private_label = tnow_privacy_service.label_for(telegram_user_id=user_id, surface=surface)
    if private_label:
        return private_label

    # Regra musical existente: o nome do mosaico prioriza o username Last.fm.
    # Telegram é somente fallback quando não existe Last.fm cadastrado.
    if lastfm_username and str(lastfm_username).strip():
        return str(lastfm_username).strip()
    lastfm_username = _lastfm_display_name(user_id)
    if lastfm_username:
        return lastfm_username

    try:
        chat = await bot.get_chat(user_id)
        name = getattr(chat, "full_name", None) or getattr(chat, "first_name", None)
        if name:
            return name
        username = getattr(chat, "username", None)
        if username:
            return f"@{username}"
    except Exception:
        logger.debug("TNOW_GET_CHAT_FAILED | user_id=%s", user_id, exc_info=True)

    return TPV_DEFAULT_LABEL


async def _warm_cover_cache(bot: Any, activity: TnowActivityHit) -> str | None:
    """Arquiva a capa no canal técnico quando possível, sem bloquear o mosaico."""
    if not activity.cover_url:
        return None
    try:
        resolved = await cover_cache_service.resolve_photo(
            bot,
            track_id=activity.track_id,
            cover_url=activity.cover_url,
        )
        if isinstance(resolved, str) and resolved and resolved != activity.cover_url:
            await tnow_activity_cache_service.update_cover_file_id(
                user_id=activity.user_id,
                cover_file_id=resolved,
            )
            return resolved
    except Exception:
        logger.debug("TNOW_COVER_CACHE_WARM_FAILED | user_id=%s", activity.user_id, exc_info=True)
    return None


async def _cover_bytes_for_activity(bot: Any, activity: TnowActivityHit) -> bytes | None:
    """Resolve capa para renderização do mosaico, cache Telegram primeiro.

    O canal técnico guarda file_id; para compor o JPEG do mosaico precisamos
    baixar bytes. Se o file_id falhar, invalidamos a referência quando possível
    e caímos para a URL original.
    """
    if activity.cover_file_id:
        data = await cover_cache_service.resolve_photo_bytes(
            bot,
            track_id=activity.track_id,
            cover_url=activity.cover_url,
            file_id=activity.cover_file_id,
        )
        if data:
            return data
        if activity.cover_url:
            await cover_cache_service.forget(
                track_id=activity.track_id,
                cover_url=activity.cover_url,
                photo=activity.cover_url,
            )
            await tnow_activity_cache_service.update_cover_file_id(
                user_id=activity.user_id,
                cover_file_id="",
            )
            logger.info(
                "TNOW_COVER_FILE_ID_INVALIDATED | user_id=%s | track_id=%s",
                activity.user_id,
                activity.track_id,
            )

    if activity.cover_url:
        cached = await cover_cache_service.resolve_photo_bytes(
            bot,
            track_id=activity.track_id,
            cover_url=activity.cover_url,
        )
        if cached:
            return cached

    return await _fetch_cover(activity.cover_url)


async def _refresh_recent_activity(bot: Any, user_id: int, *, now: datetime) -> None:
    track = await _resolve_now_playing(user_id, now=now)
    if not track:
        logger.info("TNOW_ENTRY_DECISION | user_id=%s | status=empty | selected=false", user_id)
        return

    lastfm_username = _lastfm_display_name(user_id)
    if track.get("_tnow_status") == "expired":
        # Não apaga um cache ainda válido por causa de uma consulta instantânea
        # antiga ou falha parcial de outro provedor. O filtro por `expires_at`
        # remove naturalmente qualquer registro acima de 2h.
        logger.info(
            "TNOW_ENTRY_DECISION | user_id=%s | lastfm_username=%s | status=expired | age_seconds=%s | selected=false",
            user_id,
            lastfm_username,
            track.get("_tnow_age_seconds"),
        )
        return

    await tnow_activity_cache_service.upsert_from_track(
        user_id=user_id,
        lastfm_username=lastfm_username,
        track=track,
        now=now,
    )


async def _entry_from_activity(bot: Any, activity: TnowActivityHit) -> TnowEntry:
    cover_bytes = await _cover_bytes_for_activity(bot, activity)
    display_name = await _display_name(bot, activity.user_id, activity.lastfm_username, surface="tnow")
    source = "spotify" if str(activity.source).startswith("spotify") else "lastfm"
    age_minutes = int(max(0.0, activity.raw_age_seconds or 0.0) // 60)
    return TnowEntry(
        user_id=activity.user_id,
        display_name=display_name,
        track_name=activity.track_name or "—",
        artist=activity.artist or "—",
        cover_bytes=cover_bytes,
        source=source,
        status=activity.status,
        age_minutes=age_minutes,
    )


_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_MEMBER_OUT_STATUSES = {"left", "kicked"}


async def _is_chat_member(bot: Any, chat_id: int, user_id: int) -> bool:
    """True se o usuário é membro ativo do chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = getattr(member, "status", None)
        status_value = getattr(status, "value", status)
        return str(status_value) not in _MEMBER_OUT_STATUSES
    except Exception:
        logger.debug(
            "TNOW_GET_CHAT_MEMBER_FAILED | chat_id=%s | user_id=%s",
            chat_id, user_id, exc_info=True,
        )
        return False


async def _filter_to_group_members(bot: Any, chat_id: int, user_ids: list[int]) -> list[int]:
    if not user_ids:
        return []
    checks = await asyncio.gather(
        *[_is_chat_member(bot, chat_id, uid) for uid in user_ids],
        return_exceptions=False,
    )
    return [uid for uid, ok in zip(user_ids, checks) if ok]


async def _gather_entries(bot: Any, chat: Chat | None = None, *, use_snapshot: bool = True) -> list[TnowEntry]:
    scope = _scope_kind(chat)
    snapshot_key = _snapshot_key(chat)
    if use_snapshot:
        cached = _get_snapshot(snapshot_key)
        if cached is not None:
            return cached

    registered_user_ids = _registered_user_ids()
    if not registered_user_ids:
        logger.info(
            "TNOW_GATHER_RESULT | scope=%s | registered=0 | members=0 | eligible=0 | selected=0 | live=0 | recent_15=0 | recent_30=0 | recent_45=0 | recent_120=0 | chat_id=%s",
            scope,
            getattr(chat, "id", None),
        )
        _put_snapshot(snapshot_key, [])
        return []

    user_ids = registered_user_ids
    if chat is not None and chat.type in _GROUP_TYPES:
        user_ids = await _filter_to_group_members(bot, chat.id, user_ids)
        if not user_ids:
            logger.info(
                "TNOW_GATHER_RESULT | scope=group | registered=%s | members=0 | eligible=0 | selected=0 | chat_id=%s",
                len(registered_user_ids),
                chat.id,
            )
            _put_snapshot(snapshot_key, [])
            return []

    now = _utcnow()
    sem = asyncio.Semaphore(TNOW_GATHER_CONCURRENCY)

    async def _guarded_refresh(uid: int) -> None:
        async with sem:
            await _refresh_recent_activity(bot, uid, now=now)

    tasks = [asyncio.create_task(_guarded_refresh(uid)) for uid in user_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    raised = 0
    for item in results:
        if isinstance(item, Exception):
            raised += 1
            logger.debug("TNOW_REFRESH_ENTRY_RAISED", exc_info=item)

    eligible = await tnow_activity_cache_service.list_for_users(user_ids, now=now)
    eligible.sort(key=_activity_sort_key)
    rows, columns, slots = _choose_grid_layout(min(len(eligible), MAX_TILES))
    selected_activities = eligible[:slots]

    # Aquece o cache de canal apenas para os selecionados. Isso evita N uploads
    # para usuários que seriam cortados pelo layout final.
    if selected_activities:
        await asyncio.gather(
            *[_warm_cover_cache(bot, activity) for activity in selected_activities],
            return_exceptions=True,
        )

    entries = [await _entry_from_activity(bot, activity) for activity in selected_activities]
    entries.sort(key=_entry_sort_key)

    counts = {"live": 0, "recent_15": 0, "recent_30": 0, "recent_45": 0, "recent_120": 0}
    for activity in eligible:
        if activity.status in counts:
            counts[activity.status] += 1

    selected_ids = {entry.user_id for entry in entries}
    for activity in eligible:
        logger.info(
            "TNOW_ENTRY_DECISION | user_id=%s | lastfm_username=%s | source=%s | status=%s | age_seconds=%s | selected=%s | grid=%sx%s | track=%s | artist=%s",
            activity.user_id,
            activity.lastfm_username,
            activity.source,
            activity.status,
            int(activity.raw_age_seconds or 0),
            str(activity.user_id in selected_ids).lower(),
            rows,
            columns,
            activity.track_name,
            activity.artist,
        )

    logger.info(
        "TNOW_GRID_SELECTED | scope=%s | eligible=%s | grid=%sx%s | rendered=%s | live=%s | recent_15=%s | recent_30=%s | recent_45=%s | recent_120=%s | chat_id=%s",
        scope,
        len(eligible),
        rows,
        columns,
        len(entries),
        counts["live"],
        counts["recent_15"],
        counts["recent_30"],
        counts["recent_45"],
        counts["recent_120"],
        getattr(chat, "id", None),
    )

    logger.info(
        "TNOW_GATHER_RESULT | scope=%s | registered=%s | members=%s | eligible=%s | selected=%s | empty=%s | raised=%s | chat_id=%s | snapshot=%s",
        scope,
        len(registered_user_ids),
        len(user_ids),
        len(eligible),
        len(entries),
        max(0, len(user_ids) - len(eligible)),
        raised,
        getattr(chat, "id", None),
        snapshot_key,
    )

    _put_snapshot(snapshot_key, entries)
    return entries


async def _finish_tnow(status: Message, *, requester_id: int) -> None:
    try:
        chat = status.chat if status.chat.type in _GROUP_TYPES else None
        scope = _scope_kind(chat)
        if scope == "universal" and not is_code_owner(requester_id):
            logger.info(
                "TNOW_UNIVERSAL_BLOCKED | user_id=%s | chat_id=%s | chat_type=%s",
                requester_id,
                getattr(status.chat, "id", None),
                getattr(status.chat, "type", None),
            )
            await status.edit_text("Mosaico universal é exclusivo do dono do código. Use /tnow dentro de um grupo.")
            return

        entries = await _gather_entries(status.bot, chat=chat)
        if not entries:
            empty_message = (
                "Ninguém cadastrado neste grupo tem dado musical real agora."
                if scope == "group"
                else "Nenhum usuário musical importado tem dado musical real agora."
            )
            await status.edit_text(empty_message)
            return

        card_bytes = await render_tnow_card(entries)
        label = "mosaico do grupo" if scope == "group" else "mosaico universal"
        caption = f"♫ <b>{label}</b> • {len(entries)} pessoa{'s' if len(entries) != 1 else ''}"
        if card_bytes:
            sent = await status.answer_photo(
                photo=BufferedInputFile(card_bytes, filename="tnow.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
            # Sprint 11: bot reage 🔥 no mosaico do grupo.
            from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_TNOW
            await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, _CARD_EMOJI_TNOW)
            return

        # Fallback textual quando Playwright não está disponível ou falhou.
        lines = [caption]
        for entry in entries:
            safe_name = html.escape(entry.display_name)
            safe_track = html.escape(entry.track_name)
            safe_artist = html.escape(entry.artist)
            lines.append(f"• <b>{safe_name}</b> — {safe_track} <i>({safe_artist})</i>")
        await status.edit_text("\n".join(lines), parse_mode="HTML")
    except Exception:
        logger.exception("TNOW_FAILED")
        try:
            await status.edit_text("Não consegui montar o mosaico agora. Tenta de novo em alguns segundos.")
        except Exception:
            logger.exception("TNOW_FAILURE_MESSAGE_FAILED")


# I4: mantém ref forte das background tasks pra GC não coletar antes do término.
_BG_TASKS: set[asyncio.Task] = set()




def _clear_tnow_snapshots_for_privacy_change() -> None:
    _TNOW_SNAPSHOTS.clear()


def _parse_tpv_args(text: str | None) -> tuple[int | None, str | None, str | None]:
    parts = str(text or "").split()
    if len(parts) < 3:
        return None, None, None
    try:
        user_id = int(parts[1])
    except Exception:
        return None, None, None
    mode_raw = parts[2].strip().lower()
    label = " ".join(parts[3:]).strip() if len(parts) > 3 else TPV_DEFAULT_LABEL
    return user_id, mode_raw, label or TPV_DEFAULT_LABEL


@router.message(Command("tpv"))
async def tpv(message: Message) -> None:
    """Owner-only DM command to mask a Telegram user as User in /tnow/mosaico.

    Usage:
    /tpv <telegram_id> tnow
    /tpv <telegram_id> mosaico
    /tpv <telegram_id> all
    /tpv <telegram_id> off
    """
    if not message.from_user:
        return
    if message.chat.type != ChatType.PRIVATE or not is_code_owner(message.from_user.id):
        return

    user_id, mode_raw, label = _parse_tpv_args(message.text)
    if user_id is None or not mode_raw:
        await message.answer("Uso: /tpv <ID Telegram> tnow|mosaico|all|off")
        return

    if mode_raw == "off":
        changed = tnow_privacy_service.disable_rule(telegram_user_id=user_id, owner_id=message.from_user.id)
        _clear_tnow_snapshots_for_privacy_change()
        await message.answer(
            f"TPV desativado para <code>{user_id}</code>." if changed else f"TPV já estava inativo para <code>{user_id}</code>.",
            parse_mode="HTML",
        )
        return

    mode = normalize_tpv_mode(mode_raw)
    if mode not in {"tnow", "mosaic", "all"}:
        await message.answer("Modo inválido. Use: tnow, mosaico, all ou off.")
        return

    rule = tnow_privacy_service.set_rule(
        telegram_user_id=user_id,
        mode=mode,
        display_label=label or TPV_DEFAULT_LABEL,
        owner_id=message.from_user.id,
    )
    _clear_tnow_snapshots_for_privacy_change()
    await message.answer(
        "TPV ativo: <code>{uid}</code> será exibido como <b>{label}</b> em <code>{mode}</code>.".format(
            uid=rule.telegram_user_id,
            label=html.escape(rule.display_label),
            mode=html.escape(rule.mode),
        ),
        parse_mode="HTML",
    )

@router.message(Command("tnow"))
async def tnow(message: Message) -> None:
    if not message.from_user:
        return
    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "tnow"):
        return
    # Quem manda /tnow sem ter conectado nada não vai aparecer no próprio
    # mosaico — orienta antes pra evitar confusão. Não bloqueia o comando:
    # ele segue mostrando quem mais tá ouvindo.
    from app.services.connection_check import connect_hint_for, is_user_connected
    if not is_user_connected(message.from_user.id):
        await message.answer(connect_hint_for(message.chat.type), parse_mode="HTML", disable_web_page_preview=True)
    # U1: chat_action enquanto resolve playing de todos + monta mosaico.
    try:
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass
    status = await message.answer("Vendo quem tá ouvindo o quê agora...")
    task = asyncio.create_task(_finish_tnow(status, requester_id=message.from_user.id))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
