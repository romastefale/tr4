"""Cache persistente de atividade musical recente para o mosaico /tnow.

Fonte de verdade: tabela `tnow_recent_tracks`.
Canal técnico: usado por `cover_cache_service` para mídia/capas; esta tabela
armazena a referência `cover_file_id` quando ela já existe.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.db.database import SessionLocal
from app.models.tnow_recent_track import TnowRecentTrack
from app.utils.datetime import utcnow_naive as _utcnow_naive

logger = logging.getLogger(__name__)

TNOW_LIVE_OBSERVED_TTL_SECONDS = 90
TNOW_RECENT_15_SECONDS = 15 * 60
TNOW_RECENT_30_SECONDS = 30 * 60
TNOW_RECENT_45_SECONDS = 45 * 60
TNOW_RECENT_120_SECONDS = 120 * 60

TNOW_STATUS_PRIORITY: dict[str, int] = {
    "live": 0,
    "recent_15": 1,
    "recent_30": 2,
    "recent_45": 3,
    "recent_120": 4,
    "expired": 99,
}


TNOW_ACCEPTED_TRACK_SOURCES = {
    "spotify_current",
    "spotify_last",
    "lastfm_current",
    "lastfm_last",
}

TNOW_STATUS_LABELS: dict[str, str] = {
    "live": "AO VIVO",
    "recent_15": "até 15min",
    "recent_30": "15–30min",
    "recent_45": "30–45min",
    "recent_120": "45min–2h",
}


@dataclass(slots=True, frozen=True)
class TnowActivityHit:
    user_id: int
    lastfm_username: str | None
    source: str
    status: str
    track_id: str | None
    track_name: str
    artist: str
    album_name: str | None
    track_url: str | None
    cover_url: str | None
    cover_file_id: str | None
    is_live: bool
    played_at: datetime | None
    observed_at: datetime
    fetched_at: datetime
    expires_at: datetime
    raw_age_seconds: float


@dataclass(slots=True, frozen=True)
class TnowStatusDecision:
    status: str
    age_seconds: float
    event_at: datetime
    expires_at: datetime


def _as_utc_naive(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return value.replace(tzinfo=None)
        except Exception:
            return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        logger.debug("TNOW_CACHE_DATETIME_PARSE_FAILED | value=%s", raw, exc_info=True)
        return None


def classify_recent_track(
    *,
    is_live: bool,
    played_at: datetime | None,
    observed_at: datetime,
    fetched_at: datetime | None = None,
    now: datetime | None = None,
) -> TnowStatusDecision | None:
    """Classifica a faixa real nas janelas do mosaico.

    `played_at` é timestamp real da API quando existe. Para nowplaying sem
    timestamp, `observed_at` é o dado real: o horário em que o bot viu a faixa
    tocando. Verde só é mantido enquanto a observação é fresca.
    """
    now = (now or _utcnow_naive()).replace(tzinfo=None)
    observed_at = observed_at.replace(tzinfo=None)
    fetched_at = (fetched_at or observed_at).replace(tzinfo=None)
    played_at = played_at.replace(tzinfo=None) if played_at is not None else None

    try:
        from datetime import timedelta
        live_expires_at = observed_at + timedelta(seconds=TNOW_RECENT_120_SECONDS)
    except Exception:
        live_expires_at = observed_at.replace(tzinfo=None)

    if is_live and (now - fetched_at).total_seconds() <= TNOW_LIVE_OBSERVED_TTL_SECONDS:
        return TnowStatusDecision(
            status="live",
            age_seconds=0.0,
            event_at=observed_at,
            expires_at=live_expires_at,
        )

    event_at = played_at or observed_at
    age_seconds = max(0.0, (now - event_at).total_seconds())
    expires_at = event_at.replace(tzinfo=None)
    try:
        from datetime import timedelta
        expires_at = event_at + timedelta(seconds=TNOW_RECENT_120_SECONDS)
    except Exception:
        pass

    if age_seconds <= TNOW_RECENT_15_SECONDS:
        status = "recent_15"
    elif age_seconds <= TNOW_RECENT_30_SECONDS:
        status = "recent_30"
    elif age_seconds <= TNOW_RECENT_45_SECONDS:
        status = "recent_45"
    elif age_seconds <= TNOW_RECENT_120_SECONDS:
        status = "recent_120"
    else:
        status = "expired"

    return TnowStatusDecision(
        status=status,
        age_seconds=age_seconds,
        event_at=event_at,
        expires_at=expires_at,
    )


def _clean_text(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _track_url(track: dict[str, Any]) -> str | None:
    for key in ("spotify_url", "track_url", "url", "album_url"):
        value = str(track.get(key) or "").strip()
        if value:
            return value
    return None


class TnowActivityCacheService:
    async def upsert_from_track(
        self,
        *,
        user_id: int,
        lastfm_username: str | None,
        track: dict[str, Any],
        now: datetime | None = None,
        cover_file_id: str | None = None,
    ) -> TnowActivityHit | None:
        now = (now or _utcnow_naive()).replace(tzinfo=None)
        raw_source = str(track.get("source") or "")
        if raw_source not in TNOW_ACCEPTED_TRACK_SOURCES and not track.get("_tnow_status"):
            logger.debug(
                "TNOW_CACHE_SKIP_UNTRUSTED_SOURCE | user_id=%s | source=%s | track=%s | artist=%s",
                user_id,
                raw_source,
                track.get("track_name"),
                track.get("artist"),
            )
            return None
        source = str(track.get("_source_tag") or raw_source or "unknown").strip() or "unknown"
        is_live = bool(track.get("_tnow_is_live")) or raw_source in {"spotify_current", "lastfm_current"}
        if raw_source == "spotify_current" and not bool(track.get("is_playing", True)):
            is_live = False

        played_at = _as_utc_naive(track.get("played_at") or track.get("_tnow_played_at_iso"))
        observed_at = _as_utc_naive(track.get("observed_at")) or now
        fetched_at = now
        decision = classify_recent_track(
            is_live=is_live,
            played_at=played_at,
            observed_at=observed_at,
            fetched_at=fetched_at,
            now=now,
        )
        if decision is None:
            return None

        track_name = _clean_text(track.get("track_name"), "—")
        artist = _clean_text(track.get("artist"), "—")
        if not track_name or not artist or track_name == "—" or artist == "—":
            return None

        track_id = _clean_text(track.get("track_id")) or None
        album_name = _clean_text(track.get("album_name") or track.get("album")) or None
        cover_url = _clean_text(track.get("album_image_url") or track.get("cover")) or None
        track_url = _track_url(track)
        username = _clean_text(lastfm_username) or None

        now_status = decision.status
        if now_status == "expired":
            await self.expire_user(user_id=user_id, now=now)
            logger.info(
                "TNOW_CACHE_EXPIRED_SOURCE | user_id=%s | lastfm_username=%s | track=%s | artist=%s | age_seconds=%s",
                user_id,
                username,
                track_name,
                artist,
                int(decision.age_seconds),
            )
            return None

        with SessionLocal() as db:
            row = db.get(TnowRecentTrack, user_id)
            if row is None:
                row = TnowRecentTrack(
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                    lastfm_username=username,
                    source=source,
                    status=now_status,
                    track_id=track_id,
                    track_name=track_name,
                    artist=artist,
                    album_name=album_name,
                    track_url=track_url,
                    cover_url=cover_url,
                    cover_file_id=cover_file_id,
                    is_live=is_live,
                    played_at=played_at,
                    observed_at=observed_at,
                    fetched_at=fetched_at,
                    expires_at=decision.expires_at,
                    raw_age_seconds=decision.age_seconds,
                )
                db.add(row)
            else:
                row.lastfm_username = username or row.lastfm_username
                row.source = source
                row.status = now_status
                row.track_id = track_id
                row.track_name = track_name
                row.artist = artist
                row.album_name = album_name
                row.track_url = track_url
                row.cover_url = cover_url
                row.cover_file_id = cover_file_id or row.cover_file_id
                row.is_live = is_live
                row.played_at = played_at
                row.observed_at = observed_at
                row.fetched_at = fetched_at
                row.expires_at = decision.expires_at
                row.raw_age_seconds = decision.age_seconds
                row.updated_at = now
            db.commit()

        logger.info(
            "TNOW_CACHE_UPSERT | user_id=%s | lastfm_username=%s | source=%s | status=%s | track=%s | artist=%s | played_at=%s | observed_at=%s | expires_at=%s | age_seconds=%s",
            user_id,
            username,
            source,
            now_status,
            track_name,
            artist,
            played_at.isoformat() if played_at else None,
            observed_at.isoformat(),
            decision.expires_at.isoformat(),
            int(decision.age_seconds),
        )
        return await self.get_user(user_id=user_id, now=now)

    async def update_cover_file_id(self, *, user_id: int, cover_file_id: str | None) -> None:
        try:
            with SessionLocal() as db:
                row = db.get(TnowRecentTrack, user_id)
                if row:
                    row.cover_file_id = cover_file_id or None
                    row.updated_at = _utcnow_naive()
                    db.commit()
        except Exception:
            logger.debug("TNOW_CACHE_COVER_FILE_ID_UPDATE_FAILED | user_id=%s", user_id, exc_info=True)

    async def expire_user(self, *, user_id: int, now: datetime | None = None) -> None:
        now = (now or _utcnow_naive()).replace(tzinfo=None)
        try:
            with SessionLocal() as db:
                row = db.get(TnowRecentTrack, user_id)
                if row:
                    row.status = "expired"
                    row.expires_at = now
                    row.updated_at = now
                    db.commit()
        except Exception:
            logger.debug("TNOW_CACHE_EXPIRE_USER_FAILED | user_id=%s", user_id, exc_info=True)

    async def get_user(self, *, user_id: int, now: datetime | None = None) -> TnowActivityHit | None:
        hits = await self.list_for_users([user_id], now=now)
        return hits[0] if hits else None

    async def list_for_users(self, user_ids: Iterable[int], *, now: datetime | None = None) -> list[TnowActivityHit]:
        ids = [int(uid) for uid in user_ids if uid is not None]
        if not ids:
            return []
        now = (now or _utcnow_naive()).replace(tzinfo=None)
        rows: list[TnowRecentTrack]
        with SessionLocal() as db:
            rows = (
                db.query(TnowRecentTrack)
                .filter(TnowRecentTrack.user_id.in_(ids))
                .filter(TnowRecentTrack.expires_at > now)
                .all()
            )

        out: list[TnowActivityHit] = []
        for row in rows:
            decision = classify_recent_track(
                is_live=bool(row.is_live),
                played_at=row.played_at,
                observed_at=row.observed_at,
                fetched_at=row.fetched_at,
                now=now,
            )
            if decision is None or decision.status == "expired":
                continue
            out.append(
                TnowActivityHit(
                    user_id=int(row.user_id),
                    lastfm_username=row.lastfm_username,
                    source=row.source,
                    status=decision.status,
                    track_id=row.track_id,
                    track_name=row.track_name,
                    artist=row.artist,
                    album_name=row.album_name,
                    track_url=row.track_url,
                    cover_url=row.cover_url,
                    cover_file_id=row.cover_file_id,
                    is_live=bool(row.is_live),
                    played_at=row.played_at,
                    observed_at=row.observed_at,
                    fetched_at=row.fetched_at,
                    expires_at=row.expires_at,
                    raw_age_seconds=decision.age_seconds,
                )
            )
        return out


tnow_activity_cache_service = TnowActivityCacheService()

def schedule_tnow_activity_record(user_id: int | None, track: dict[str, Any] | None, *, context: str = "music_flow") -> None:
    """Fire-and-forget recording of real music activity for the /tnow cache.

    This is intentionally non-blocking. Command/inline/WebApp delivery must not
    fail if the cache write or Last.fm username lookup fails.
    """
    if user_id is None or not track:
        return
    try:
        safe_user_id = int(user_id)
    except Exception:
        return
    payload = dict(track)

    async def _runner() -> None:
        lastfm_username: str | None = None
        try:
            from app.services.lastfm import lastfm_service  # local import avoids startup cycles

            lastfm_username = await lastfm_service.get_username(safe_user_id)
        except Exception:
            logger.debug(
                "TNOW_ACTIVITY_LASTFM_USERNAME_LOOKUP_FAILED | user_id=%s | context=%s",
                safe_user_id,
                context,
                exc_info=True,
            )
        try:
            await tnow_activity_cache_service.upsert_from_track(
                user_id=safe_user_id,
                lastfm_username=lastfm_username,
                track=payload,
            )
            logger.info(
                "TNOW_ACTIVITY_RECORD_SCHEDULED | user_id=%s | context=%s | source=%s | track=%s | artist=%s",
                safe_user_id,
                context,
                payload.get("source"),
                payload.get("track_name"),
                payload.get("artist"),
            )
        except Exception:
            logger.debug(
                "TNOW_ACTIVITY_RECORD_FAILED | user_id=%s | context=%s",
                safe_user_id,
                context,
                exc_info=True,
            )

    try:
        asyncio.create_task(_runner())
    except RuntimeError:
        logger.debug("TNOW_ACTIVITY_RECORD_NO_RUNNING_LOOP | user_id=%s | context=%s", safe_user_id, context)

