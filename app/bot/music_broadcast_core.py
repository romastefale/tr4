"""Pure helpers and persistence for TR4 music broadcast."""
from __future__ import annotations

import html
import random
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class BroadcastTarget:
    chat_id: int
    title: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_music_key(value: object) -> str:
    text_value = str(value or "").strip().lower()
    text_value = re.sub(r"\s+", " ", text_value)
    text_value = re.sub(r"[^0-9a-zà-ÿ\s]+", "", text_value, flags=re.IGNORECASE)
    return text_value.strip()


def track_identity(track: dict[str, Any]) -> dict[str, str]:
    """Return the canonical broadcast identity for Last.fm/Spotify-like payloads.

    Etapa 12: the TR4 Last.fm and Spotify services expose artwork/link as
    ``album_image_url`` and ``spotify_url``. The broadcast layer previously
    ignored those keys and could reject valid tracks as "sem card/canvas".
    """
    artist = str(track.get("artist") or track.get("artist_name") or "").strip()
    name = str(track.get("track_name") or track.get("name") or track.get("title") or "").strip()
    track_id = str(track.get("track_id") or track.get("id") or track.get("spotify_id") or "").strip()
    cover = str(
        track.get("cover")
        or track.get("album_image_url")
        or track.get("album_image")
        or track.get("cover_url")
        or track.get("image_url")
        or track.get("image")
        or ""
    ).strip()
    url = str(
        track.get("track_url")
        or track.get("spotify_url")
        or track.get("url")
        or track.get("album_url")
        or ""
    ).strip()
    return {"artist": artist, "track_name": name, "track_id": track_id, "cover": cover, "url": url}


def _db_defaults():
    from sqlalchemy import text
    from app.db.database import engine as default_engine
    return text, default_engine


def ensure_music_broadcast_tables(db_engine: "Engine | None" = None) -> None:
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_music_broadcast_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_type TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                raw_value TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(block_type, normalized_value)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_music_broadcast_runs (
                run_ref TEXT PRIMARY KEY,
                actor_user_id INTEGER NOT NULL,
                actor_kind TEXT NOT NULL,
                track_name TEXT NOT NULL,
                artist TEXT NOT NULL,
                source TEXT NOT NULL,
                total_targets INTEGER NOT NULL,
                sent_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_music_broadcast_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ref TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                message_id INTEGER,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_music_broadcast_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_ref TEXT NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                title TEXT,
                times_csv TEXT NOT NULL,
                times_per_day INTEGER NOT NULL DEFAULT 1,
                paused INTEGER NOT NULL DEFAULT 0,
                fixar INTEGER NOT NULL DEFAULT 0,
                silent INTEGER NOT NULL DEFAULT 0,
                preview_confirmed INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_run_slot TEXT,
                last_run_at TEXT,
                sent_today_date TEXT,
                sent_today_count INTEGER NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_music_broadcast_schedules_due ON eq_music_broadcast_schedules(paused, chat_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_music_broadcast_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_ref TEXT NOT NULL UNIQUE,
                artist TEXT NOT NULL,
                track_name TEXT NOT NULL,
                cover_url TEXT,
                spotify_url TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_music_broadcast_catalog_enabled ON eq_music_broadcast_catalog(enabled, updated_at)"))



def list_music_broadcast_blocks(db_engine: "Engine | None" = None) -> list[dict[str, Any]]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT id, block_type, normalized_value, raw_value, created_by, created_at
                FROM eq_music_broadcast_blocks
                ORDER BY created_at DESC, id DESC
            """)
        ).mappings().all()
    return [
        {
            "id": int(row["id"]),
            "block_ref": f"mbb_{int(row['id'])}",
            "block_type": str(row["block_type"]),
            "normalized_value": str(row["normalized_value"]),
            "raw_value": str(row["raw_value"]),
            "created_by": row.get("created_by"),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def remove_music_broadcast_block(*, block_id: int, db_engine: "Engine | None" = None) -> bool:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        result = conn.execute(text("DELETE FROM eq_music_broadcast_blocks WHERE id=:id"), {"id": int(block_id)})
    return bool(getattr(result, "rowcount", 0))


def _clean_schedule_times(times: object) -> list[str]:
    if isinstance(times, (list, tuple, set)):
        raw_parts = list(times)
    else:
        raw_parts = re.split(r"[,;\s]+", str(times or ""))
    out: list[str] = []
    for part in raw_parts:
        value = str(part or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
        if not match:
            continue
        hour = int(match.group(1)); minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            item = f"{hour:02d}:{minute:02d}"
            if item not in out:
                out.append(item)
    return sorted(out)


def _local_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    if now.tzinfo is None:
        return now.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    return now.astimezone(ZoneInfo("America/Sao_Paulo"))


def create_music_broadcast_schedule(
    *,
    chat_id: int,
    title: str,
    times: object,
    times_per_day: int = 1,
    created_by: int | None = None,
    paused: bool = False,
    fixar: bool = False,
    silent: bool = False,
    preview_confirmed: bool = False,
    db_engine: "Engine | None" = None,
) -> dict[str, Any]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    clean_times = _clean_schedule_times(times)
    if not clean_times:
        raise ValueError("horário automático inválido")
    now = _now_iso()
    schedule_ref = f"mbs_{uuid.uuid4().hex[:14]}"
    with db_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO eq_music_broadcast_schedules (
                    schedule_ref, chat_id, title, times_csv, times_per_day, paused, fixar, silent,
                    preview_confirmed, created_by, created_at, updated_at, sent_today_count
                ) VALUES (
                    :schedule_ref, :chat_id, :title, :times_csv, :times_per_day, :paused, :fixar, :silent,
                    :preview_confirmed, :created_by, :created_at, :updated_at, 0
                )
            """),
            {
                "schedule_ref": schedule_ref,
                "chat_id": int(chat_id),
                "title": str(title or "Grupo")[:120],
                "times_csv": ",".join(clean_times),
                "times_per_day": max(1, min(int(times_per_day or 1), len(clean_times))),
                "paused": 1 if paused else 0,
                "fixar": 1 if fixar else 0,
                "silent": 1 if silent else 0,
                "preview_confirmed": 1 if preview_confirmed else 0,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_music_broadcast_schedule(schedule_ref=schedule_ref, db_engine=db_engine) or {"schedule_ref": schedule_ref}


def _schedule_public(row: object) -> dict[str, Any]:
    return {
        "schedule_ref": str(row["schedule_ref"]),
        "chat_id": int(row["chat_id"]),
        "title": str(row.get("title") or "Grupo"),
        "times": _clean_schedule_times(row.get("times_csv")),
        "times_per_day": int(row.get("times_per_day") or 1),
        "paused": bool(int(row.get("paused") or 0)),
        "fixar": bool(int(row.get("fixar") or 0)),
        "silent": bool(int(row.get("silent") or 0)),
        "preview_confirmed": bool(int(row.get("preview_confirmed") or 0)),
        "created_by": row.get("created_by"),
        "updated_at": str(row.get("updated_at") or ""),
        "last_run_slot": str(row.get("last_run_slot") or ""),
        "last_run_at": str(row.get("last_run_at") or ""),
        "sent_today_date": str(row.get("sent_today_date") or ""),
        "sent_today_count": int(row.get("sent_today_count") or 0),
    }


def get_music_broadcast_schedule(*, schedule_ref: str, db_engine: "Engine | None" = None) -> dict[str, Any] | None:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT schedule_ref, chat_id, title, times_csv, times_per_day, paused, fixar, silent,
                       preview_confirmed, created_by, updated_at, last_run_slot, last_run_at,
                       sent_today_date, sent_today_count
                FROM eq_music_broadcast_schedules
                WHERE schedule_ref=:schedule_ref
                LIMIT 1
            """),
            {"schedule_ref": str(schedule_ref or "").strip()},
        ).mappings().first()
    return _schedule_public(row) if row else None


def list_music_broadcast_schedules(db_engine: "Engine | None" = None) -> list[dict[str, Any]]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT schedule_ref, chat_id, title, times_csv, times_per_day, paused, fixar, silent,
                       preview_confirmed, created_by, updated_at, last_run_slot, last_run_at,
                       sent_today_date, sent_today_count
                FROM eq_music_broadcast_schedules
                ORDER BY updated_at DESC, id DESC
            """)
        ).mappings().all()
    return [_schedule_public(row) for row in rows]


def set_music_broadcast_schedule_paused(*, schedule_ref: str, paused: bool, db_engine: "Engine | None" = None) -> bool:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        result = conn.execute(
            text("UPDATE eq_music_broadcast_schedules SET paused=:paused, updated_at=:updated_at WHERE schedule_ref=:schedule_ref"),
            {"paused": 1 if paused else 0, "updated_at": _now_iso(), "schedule_ref": str(schedule_ref or "").strip()},
        )
    return bool(getattr(result, "rowcount", 0))


def delete_music_broadcast_schedule(*, schedule_ref: str, db_engine: "Engine | None" = None) -> bool:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        result = conn.execute(text("DELETE FROM eq_music_broadcast_schedules WHERE schedule_ref=:schedule_ref"), {"schedule_ref": str(schedule_ref or "").strip()})
    return bool(getattr(result, "rowcount", 0))


def due_music_broadcast_schedules(*, now: datetime | None = None, db_engine: "Engine | None" = None) -> list[dict[str, Any]]:
    ensure_music_broadcast_tables(db_engine)
    local_now = _local_now(now)
    today = local_now.date().isoformat()
    current_slot = f"{local_now.hour:02d}:{local_now.minute:02d}"
    due: list[dict[str, Any]] = []
    for row in list_music_broadcast_schedules(db_engine=db_engine):
        if row.get("paused") or not row.get("preview_confirmed"):
            continue
        sent_date = str(row.get("sent_today_date") or "")
        sent_count = int(row.get("sent_today_count") or 0) if sent_date == today else 0
        if sent_count >= int(row.get("times_per_day") or 1):
            continue
        for slot in row.get("times") or []:
            run_slot = f"{today}#{slot}"
            # Etapa 12: do not catch up old slots after restart/manual processing.
            # A schedule runs only during the exact local minute configured.
            if slot == current_slot and str(row.get("last_run_slot") or "") != run_slot:
                item = dict(row)
                item["due_slot"] = run_slot
                due.append(item)
                break
    return due


def mark_music_broadcast_schedule_run(*, schedule_ref: str, due_slot: str, sent: bool, db_engine: "Engine | None" = None) -> None:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    today = str(due_slot or "").split("#", 1)[0]
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT sent_today_date, sent_today_count FROM eq_music_broadcast_schedules WHERE schedule_ref=:schedule_ref"),
            {"schedule_ref": str(schedule_ref or "").strip()},
        ).mappings().first()
        previous_date = str((row or {}).get("sent_today_date") or "")
        previous_count = int((row or {}).get("sent_today_count") or 0) if previous_date == today else 0
        next_count = previous_count + (1 if sent else 0)
        conn.execute(
            text("""
                UPDATE eq_music_broadcast_schedules
                SET last_run_slot=:due_slot, last_run_at=:last_run_at,
                    sent_today_date=:today, sent_today_count=:sent_today_count, updated_at=:updated_at
                WHERE schedule_ref=:schedule_ref
            """),
            {
                "due_slot": str(due_slot or ""),
                "last_run_at": _now_iso(),
                "today": today,
                "sent_today_count": next_count,
                "updated_at": _now_iso(),
                "schedule_ref": str(schedule_ref or "").strip(),
            },
        )


def music_broadcast_config_public(db_engine: "Engine | None" = None) -> dict[str, Any]:
    blocks = list_music_broadcast_blocks(db_engine=db_engine)
    schedules = list_music_broadcast_schedules(db_engine=db_engine)
    catalog = list_manual_music_catalog(db_engine=db_engine)
    return {
        "blocks": blocks,
        "schedules": schedules,
        "catalog": catalog,
        "resumo": {
            "bloqueios": len(blocks),
            "agendamentos": len(schedules),
            "catalogo_manual": len([row for row in catalog if row.get("enabled")]),
        },
    }

def add_music_broadcast_block(*, block_type: str, value: str, created_by: int | None = None, db_engine: "Engine | None" = None) -> None:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    block_type_clean = str(block_type or "").strip().lower()
    if block_type_clean not in {"artist", "track"}:
        raise ValueError("block_type must be artist or track")
    normalized = normalize_music_key(value)
    if not normalized:
        raise ValueError("empty block value")
    with db_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO eq_music_broadcast_blocks (block_type, normalized_value, raw_value, created_by, created_at)
                VALUES (:block_type, :normalized_value, :raw_value, :created_by, :created_at)
                ON CONFLICT(block_type, normalized_value) DO UPDATE SET
                    raw_value=excluded.raw_value,
                    created_by=excluded.created_by
            """),
            {"block_type": block_type_clean, "normalized_value": normalized, "raw_value": value, "created_by": created_by, "created_at": _now_iso()},
        )


def is_music_broadcast_blocked(track: dict[str, Any], db_engine: "Engine | None" = None) -> tuple[bool, str]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    info = track_identity(track)
    artist_key = normalize_music_key(info["artist"])
    track_key = normalize_music_key(info["track_name"])
    if not (artist_key or track_key):
        return True, "música sem identificação"
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT block_type, raw_value
                FROM eq_music_broadcast_blocks
                WHERE (block_type='artist' AND normalized_value=:artist)
                   OR (block_type='track' AND normalized_value=:track)
                LIMIT 1
            """),
            {"artist": artist_key, "track": track_key},
        ).mappings().all()
    if rows:
        row = rows[0]
        return True, f"bloqueio global de {row['block_type']}: {row['raw_value']}"
    return False, ""



def _catalog_ref_for(*, artist: str, track_name: str, created_at: str) -> str:
    seed = f"{normalize_music_key(artist)}:{normalize_music_key(track_name)}:{created_at}:{uuid.uuid4().hex[:8]}"
    return "mbcat_" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:14]


def add_manual_music_catalog_item(
    *,
    artist: str,
    track_name: str,
    cover_url: str = "",
    spotify_url: str = "",
    created_by: int | None = None,
    enabled: bool = True,
    db_engine: "Engine | None" = None,
) -> dict[str, Any]:
    """Add a manual owner track to the automatic broadcast catalog."""
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    safe_artist = str(artist or "").strip()[:160]
    safe_track = str(track_name or "").strip()[:180]
    if not safe_artist or not safe_track:
        raise ValueError("artista e música são obrigatórios")
    now = _now_iso()
    catalog_ref = _catalog_ref_for(artist=safe_artist, track_name=safe_track, created_at=now)
    with db_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO eq_music_broadcast_catalog (
                    catalog_ref, artist, track_name, cover_url, spotify_url, enabled,
                    created_by, created_at, updated_at, use_count
                ) VALUES (
                    :catalog_ref, :artist, :track_name, :cover_url, :spotify_url, :enabled,
                    :created_by, :created_at, :updated_at, 0
                )
            """),
            {
                "catalog_ref": catalog_ref,
                "artist": safe_artist,
                "track_name": safe_track,
                "cover_url": str(cover_url or "").strip()[:600],
                "spotify_url": str(spotify_url or "").strip()[:600],
                "enabled": 1 if enabled else 0,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_manual_music_catalog_item(catalog_ref=catalog_ref, db_engine=db_engine) or {"catalog_ref": catalog_ref}


def _catalog_public(row: object) -> dict[str, Any]:
    return {
        "catalog_ref": str(row["catalog_ref"]),
        "artist": str(row.get("artist") or ""),
        "track_name": str(row.get("track_name") or ""),
        "cover_url": str(row.get("cover_url") or ""),
        "spotify_url": str(row.get("spotify_url") or ""),
        "enabled": bool(int(row.get("enabled") or 0)),
        "created_by": row.get("created_by"),
        "updated_at": str(row.get("updated_at") or ""),
        "last_used_at": str(row.get("last_used_at") or ""),
        "use_count": int(row.get("use_count") or 0),
    }


def get_manual_music_catalog_item(*, catalog_ref: str, db_engine: "Engine | None" = None) -> dict[str, Any] | None:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT catalog_ref, artist, track_name, cover_url, spotify_url, enabled,
                       created_by, updated_at, last_used_at, use_count
                FROM eq_music_broadcast_catalog
                WHERE catalog_ref=:catalog_ref
                LIMIT 1
            """),
            {"catalog_ref": str(catalog_ref or "").strip()},
        ).mappings().first()
    return _catalog_public(row) if row else None


def list_manual_music_catalog(*, enabled_only: bool = False, db_engine: "Engine | None" = None) -> list[dict[str, Any]]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    where = "WHERE enabled=1" if enabled_only else ""
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(f"""
                SELECT catalog_ref, artist, track_name, cover_url, spotify_url, enabled,
                       created_by, updated_at, last_used_at, use_count
                FROM eq_music_broadcast_catalog
                {where}
                ORDER BY enabled DESC, use_count ASC, updated_at DESC
                LIMIT 250
            """),
        ).mappings().all()
    return [_catalog_public(row) for row in rows]


def remove_manual_music_catalog_item(*, catalog_ref: str, db_engine: "Engine | None" = None) -> bool:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        result = conn.execute(
            text("UPDATE eq_music_broadcast_catalog SET enabled=0, updated_at=:updated_at WHERE catalog_ref=:catalog_ref"),
            {"updated_at": _now_iso(), "catalog_ref": str(catalog_ref or "").strip()},
        )
    return bool(getattr(result, "rowcount", 0))


def mark_manual_catalog_used(*, catalog_ref: str, db_engine: "Engine | None" = None) -> None:
    if not catalog_ref:
        return
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    with db_engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE eq_music_broadcast_catalog
                SET last_used_at=:now, use_count=COALESCE(use_count,0)+1, updated_at=:now
                WHERE catalog_ref=:catalog_ref
            """),
            {"now": _now_iso(), "catalog_ref": str(catalog_ref)},
        )


def catalog_item_to_track(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "artist": str(item.get("artist") or ""),
        "track_name": str(item.get("track_name") or ""),
        "cover_url": str(item.get("cover_url") or ""),
        "spotify_url": str(item.get("spotify_url") or ""),
        "source": "manual_catalog",
        "catalog_ref": str(item.get("catalog_ref") or ""),
    }


def _recent_broadcast_keys(*, db_engine: "Engine | None" = None, limit: int = 40) -> tuple[set[str], set[str]]:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    tracks: set[str] = set()
    artists: set[str] = set()
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT track_name, artist
                FROM eq_music_broadcast_runs
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": int(limit)},
        ).mappings().all()
    for row in rows:
        t = normalize_music_key(row.get("track_name"))
        a = normalize_music_key(row.get("artist"))
        if t:
            tracks.add(t)
        if a:
            artists.add(a)
    return tracks, artists


def choose_manual_catalog_track(*, db_engine: "Engine | None" = None) -> dict[str, Any] | None:
    """Choose a manual catalog track, avoiding recent repetitions when possible."""
    items = list_manual_music_catalog(enabled_only=True, db_engine=db_engine)
    if not items:
        return None
    recent_tracks, recent_artists = _recent_broadcast_keys(db_engine=db_engine)
    eligible: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for item in items:
        track = catalog_item_to_track(item)
        info = track_identity(track)
        if not (info["track_name"] and info["artist"] and info["cover"]):
            continue
        blocked, _reason = is_music_broadcast_blocked(track, db_engine=db_engine)
        if blocked:
            continue
        key_track = normalize_music_key(info["track_name"])
        key_artist = normalize_music_key(info["artist"])
        fallback.append(track)
        if key_track not in recent_tracks and key_artist not in recent_artists:
            eligible.append(track)
    pool = eligible or fallback
    if not pool:
        return None
    chosen = random.choice(pool)
    return chosen

def build_music_broadcast_caption(track: dict[str, Any], *, listener_name: str, actor_label: str = "TR4") -> str:
    info = track_identity(track)
    track_name = html.escape(info["track_name"] or "Música")
    artist = html.escape(info["artist"] or "Artista")
    listener = html.escape(str(listener_name or "Grupo").strip()[:80] or "Grupo")
    actor = html.escape(str(actor_label or "TR4").strip()[:80] or "TR4")
    if info["url"]:
        track_part = f'<a href="{html.escape(info["url"], quote=True)}"><b>{track_name}</b></a>'
    else:
        track_part = f"<b>{track_name}</b>"
    return f"{listener} · ♫\n\n{track_part} — <i>{artist}</i>\n<blockquote>Transmitido por {actor}</blockquote>"


def targets_from_music_groups(groups: Iterable[dict[str, Any]]) -> list[BroadcastTarget]:
    targets: list[BroadcastTarget] = []
    for row in groups:
        try:
            chat_id = int(row.get("chat_id") or 0)
        except Exception:
            continue
        if not chat_id:
            continue
        title = str(row.get("title") or row.get("username") or "Grupo").strip()[:80] or "Grupo"
        targets.append(BroadcastTarget(chat_id=chat_id, title=title))
    return targets


def selection_from_arg(arg: str, groups: list[BroadcastTarget]) -> list[BroadcastTarget]:
    value = str(arg or "").strip().lower()
    if value == "all":
        return groups[:25]
    indexes: list[int] = []
    for part in re.split(r"[,\s]+", value):
        if part.isdigit():
            indexes.append(int(part))
    selected: list[BroadcastTarget] = []
    for idx in indexes:
        if 1 <= idx <= len(groups):
            selected.append(groups[idx - 1])
    return selected[:25]


def summarize_run(run_ref: str, results: list[dict[str, Any]], *, blocked_reason: str = "") -> dict[str, Any]:
    sent = sum(1 for item in results if item.get("status") == "enviado")
    failed = sum(1 for item in results if item.get("status") == "falhou")
    skipped = sum(1 for item in results if item.get("status") == "bloqueado")
    resumo = f"Broadcast musical: {sent} enviado(s), {skipped} bloqueado(s), {failed} falha(s)."
    if blocked_reason:
        resumo += f" Motivo: {blocked_reason}."
    return {"ok": True, "run_ref": run_ref, "enviados": sent, "bloqueados": skipped, "falhas": failed, "resumo": resumo, "resultados": results}


def record_music_broadcast_run(
    *,
    run_ref: str,
    actor_user_id: int,
    actor_kind: str,
    track: dict[str, Any],
    results: list[dict[str, Any]],
    db_engine: "Engine | None" = None,
) -> None:
    ensure_music_broadcast_tables(db_engine)
    text, default_engine = _db_defaults()
    db_engine = db_engine or default_engine
    info = track_identity(track)
    sent = sum(1 for item in results if item.get("status") == "enviado")
    failed = sum(1 for item in results if item.get("status") == "falhou")
    skipped = sum(1 for item in results if item.get("status") == "bloqueado")
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO eq_music_broadcast_runs
                (run_ref, actor_user_id, actor_kind, track_name, artist, source, total_targets, sent_count, failed_count, skipped_count, created_at)
                VALUES (:run_ref, :actor_user_id, :actor_kind, :track_name, :artist, :source, :total_targets, :sent_count, :failed_count, :skipped_count, :created_at)
            """),
            {
                "run_ref": run_ref,
                "actor_user_id": int(actor_user_id),
                "actor_kind": actor_kind,
                "track_name": info["track_name"],
                "artist": info["artist"],
                "source": str(track.get("source") or track.get("provider") or "music_service"),
                "total_targets": len(results),
                "sent_count": sent,
                "failed_count": failed,
                "skipped_count": skipped,
                "created_at": now,
            },
        )
        for item in results:
            conn.execute(
                text("""
                    INSERT INTO eq_music_broadcast_results (run_ref, chat_id, status, message_id, reason, created_at)
                    VALUES (:run_ref, :chat_id, :status, :message_id, :reason, :created_at)
                """),
                {
                    "run_ref": run_ref,
                    "chat_id": int(item.get("chat_id") or 0),
                    "status": str(item.get("status") or "falhou"),
                    "message_id": item.get("message_id"),
                    "reason": str(item.get("reason") or "")[:240],
                    "created_at": now,
                },
            )
