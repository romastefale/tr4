from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app.db.database import SessionLocal
from app.models.lyrics_snippet_cache import LyricsSnippetCache
from app.utils.datetime import utcnow_naive as _utcnow_naive

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_lyrics_key_part(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def build_lyrics_cache_key(artist: str | None, title: str | None) -> str | None:
    artist_norm = normalize_lyrics_key_part(artist)
    title_norm = normalize_lyrics_key_part(title)
    if not artist_norm or not title_norm:
        return None
    digest = hashlib.sha1(f"{artist_norm}\0{title_norm}".encode("utf-8")).hexdigest()
    return f"lyr:{digest}"


@dataclass(slots=True)
class LyricsCacheHit:
    snippet: str | None
    source: str | None
    negative: bool = False


class LyricsSnippetCacheService:
    """Cache persistente para /tly, inline e WebApp.

    Não guarda letra completa: só o trecho final exibido ao usuário. Cache
    negativo tem TTL curto e serve apenas para evitar martelar fontes externas
    instáveis no mesmo minuto.
    """

    async def get(self, artist: str, title: str) -> LyricsCacheHit | None:
        key = build_lyrics_cache_key(artist, title)
        if not key:
            return None
        now = _utcnow_naive()
        try:
            with SessionLocal() as db:
                row = db.get(LyricsSnippetCache, key)
                if not row:
                    return None
                if row.expires_at <= now:
                    db.delete(row)
                    db.commit()
                    return None
                if row.snippet:
                    logger.info("LYRICS_DB_HIT artist=%s title=%s source=%s", artist, title, row.source or "db")
                    return LyricsCacheHit(snippet=row.snippet, source=row.source or "db", negative=False)
                logger.info("LYRICS_DB_NEGATIVE_HIT artist=%s title=%s", artist, title)
                return LyricsCacheHit(snippet=None, source=row.source or "negative", negative=True)
        except Exception:
            logger.warning("lyrics_cache get failed artist=%s title=%s", artist, title, exc_info=True)
            return None

    async def put(
        self,
        *,
        artist: str,
        title: str,
        snippet: str | None,
        source: str | None,
        ttl_seconds: int,
    ) -> None:
        key = build_lyrics_cache_key(artist, title)
        if not key:
            return
        artist_norm = normalize_lyrics_key_part(artist)
        title_norm = normalize_lyrics_key_part(title)
        now = _utcnow_naive()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
        clean_snippet = (snippet or "").strip() or None
        clean_source = (source or "").strip() or ("db" if clean_snippet else "negative")
        try:
            with SessionLocal() as db:
                try:
                    row = db.get(LyricsSnippetCache, key)
                    if row:
                        row.artist_norm = artist_norm
                        row.title_norm = title_norm
                        row.artist = artist
                        row.title = title
                        row.snippet = clean_snippet
                        row.source = clean_source
                        row.expires_at = expires_at
                        row.updated_at = now
                    else:
                        db.add(
                            LyricsSnippetCache(
                                cache_key=key,
                                artist_norm=artist_norm,
                                title_norm=title_norm,
                                artist=artist,
                                title=title,
                                snippet=clean_snippet,
                                source=clean_source,
                                expires_at=expires_at,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    row = db.get(LyricsSnippetCache, key)
                    if row:
                        row.snippet = clean_snippet
                        row.source = clean_source
                        row.expires_at = expires_at
                        row.updated_at = now
                        db.commit()
        except Exception:
            logger.warning("lyrics_cache put failed artist=%s title=%s", artist, title, exc_info=True)

    async def forget(self, artist: str, title: str) -> None:
        key = build_lyrics_cache_key(artist, title)
        if not key:
            return
        try:
            with SessionLocal() as db:
                row = db.get(LyricsSnippetCache, key)
                if row:
                    db.delete(row)
                    db.commit()
        except Exception:
            logger.warning("lyrics_cache forget failed artist=%s title=%s", artist, title, exc_info=True)


lyrics_snippet_cache_service = LyricsSnippetCacheService()
