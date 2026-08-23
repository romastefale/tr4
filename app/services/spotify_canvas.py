from __future__ import annotations

import asyncio
import logging
import re
import time
import weakref

import httpx

from app.config.settings import (
    SPOTIFY_CANVAS_ENABLED,
    SPOTIFY_CANVAS_SP_DC,
    SPOTIFY_CANVAS_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

CANVAS_URL_CACHE_TTL_SECONDS = 24 * 3600
CANVAS_URL_NEGATIVE_TTL_SECONDS = 1 * 3600
CANVAS_DOWNLOAD_MAX_BYTES = 8 * 1024 * 1024
CANVAS_DOWNLOAD_TIMEOUT_SECONDS = 10.0
CANVAS_URL_RE = re.compile(rb"https://canvaz\.scdn\.co/[^\x00\s\"'<>]+")

CANVASDOWNLOADER_URL = "https://www.canvasdownloader.com/canvas"
CANVASDOWNLOADER_TIMEOUT_SECONDS = 8.0
CANVASDOWNLOADER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
    "Referer": "https://www.canvasdownloader.com/",
}
CANVASDOWNLOADER_NOT_FOUND_MARKER = "Canvas not found"


class SpotifyCanvasService:
    """Last-step Canvas resolver.

    Meio A: canvasdownloader.com (sem sp_dc nosso)
    Meio B: reservado / opcional (SP_DC) — nesta versão enxuta o foco é Meio A.
    Caller (deliver_canvas) cai em PLAYING_FALLBACK se ambos falharem.
    """

    def __init__(self) -> None:
        self._url_cache: dict[str, tuple[str | None, float]] = {}
        self._url_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._canvas_concurrency = asyncio.Semaphore(3)

    def _get_url_lock(self, track_id: str) -> asyncio.Lock:
        lock = self._url_locks.get(track_id)
        if lock is None:
            lock = asyncio.Lock()
            self._url_locks[track_id] = lock
        return lock

    async def get_canvas_url(self, track_id: str) -> str | None:
        clean_track_id = (track_id or "").strip()
        if not SPOTIFY_CANVAS_ENABLED:
            logger.info("Spotify Canvas skipped: disabled")
            return None
        if not clean_track_id:
            logger.info("Spotify Canvas skipped: empty track_id")
            return None
        if clean_track_id.startswith("lfm:"):
            logger.info(
                "Spotify Canvas skipped: track_id not spotify (got=%s)",
                clean_track_id,
            )
            return None

        now = time.time()
        cached = self._url_cache.get(clean_track_id)
        if cached is not None and now < cached[1]:
            return cached[0]

        async with self._get_url_lock(clean_track_id):
            now = time.time()
            cached = self._url_cache.get(clean_track_id)
            if cached is not None and now < cached[1]:
                return cached[0]
            async with self._canvas_concurrency:
                try:
                    # MEIO A — site público (sem cookie nosso)
                    canvas_url, _ = await self._fetch_via_canvasdownloader(clean_track_id)
                    if canvas_url:
                        logger.info(
                            "CANVAS_RESOLVER_A hit source=proxy track_id=%s",
                            clean_track_id,
                        )
                        self._url_cache[clean_track_id] = (
                            canvas_url,
                            time.time() + CANVAS_URL_CACHE_TTL_SECONDS,
                        )
                        logger.info(
                            "CANVAS_URL_HIT track_id=%s resolver_a=hit resolver_b=skip",
                            clean_track_id,
                        )
                        return canvas_url

                    logger.info(
                        "CANVAS_RESOLVER_A miss source=proxy track_id=%s",
                        clean_track_id,
                    )
                    # MEIO B: se SP_DC estiver setado, tentaríamos canvaz oficial.
                    # Mantido como skip nesta versão enxuta (bot leve, sem TOTP).
                    if SPOTIFY_CANVAS_SP_DC:
                        logger.info(
                            "CANVAS_RESOLVER_B skip source=token_direct "
                            "track_id=%s reason=slim_build_no_totp",
                            clean_track_id,
                        )
                    logger.info(
                        "CANVAS_URL_MISS track_id=%s resolver_a=miss resolver_b=skip",
                        clean_track_id,
                    )
                    self._url_cache[clean_track_id] = (
                        None,
                        time.time() + CANVAS_URL_NEGATIVE_TTL_SECONDS,
                    )
                    return None
                except Exception:
                    logger.exception(
                        "Spotify Canvas lookup failed: track_id=%s", clean_track_id
                    )
                    return None

    async def _fetch_via_canvasdownloader(
        self, track_id: str
    ) -> tuple[str | None, bool]:
        track_url = f"https://open.spotify.com/track/{track_id}"
        try:
            async with httpx.AsyncClient(
                timeout=CANVASDOWNLOADER_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers=CANVASDOWNLOADER_HEADERS,
            ) as client:
                response = await client.get(
                    CANVASDOWNLOADER_URL, params={"link": track_url}
                )
        except Exception:
            logger.warning(
                "Canvas proxy request error: track_id=%s", track_id, exc_info=True
            )
            return None, False
        if response.status_code != 200:
            logger.warning(
                "Canvas proxy non-200: track_id=%s status=%s",
                track_id,
                response.status_code,
            )
            return None, False
        match = CANVAS_URL_RE.search(response.content)
        if match:
            try:
                return match.group(0).decode(), False
            except UnicodeDecodeError:
                return None, False
        is_not_found = CANVASDOWNLOADER_NOT_FOUND_MARKER in response.text
        logger.info(
            "Canvas proxy MISS: track_id=%s proxy_says_not_found=%s",
            track_id,
            is_not_found,
        )
        return None, is_not_found

    async def download_canvas_bytes(self, url: str) -> bytes | None:
        if not url or not url.startswith("https://canvaz.scdn.co/"):
            logger.warning(
                "Canvas download rejected: bad url=%s",
                url[:120] if url else None,
            )
            return None
        try:
            async with httpx.AsyncClient(
                timeout=CANVAS_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "Canvas download failed: status=%s url=%s",
                            response.status_code,
                            url,
                        )
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > CANVAS_DOWNLOAD_MAX_BYTES:
                            logger.warning(
                                "Canvas download aborted: oversize url=%s", url
                            )
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
        except Exception:
            logger.exception("Canvas download error url=%s", url)
            return None


spotify_canvas_service = SpotifyCanvasService()


async def fetch_canvas_video_bytes(
    track_id: str,
    artist: str | None = None,
    track_name: str | None = None,
) -> bytes | None:
    canvas_track_id = (track_id or "").strip()
    if not canvas_track_id:
        return None
    if canvas_track_id.startswith("lfm:"):
        artist_clean = (artist or "").strip()
        track_clean = (track_name or "").strip()
        if not artist_clean or not track_clean:
            return None
        from app.services.spotify import spotify_service

        try:
            match = await spotify_service.search_track(artist_clean, track_clean)
        except Exception:
            logger.exception(
                "Canvas helper: search_track error | artist=%s | track=%s",
                artist_clean,
                track_clean,
            )
            return None
        if not match or not match.get("id"):
            return None
        canvas_track_id = match["id"]

    canvas_url = await spotify_canvas_service.get_canvas_url(canvas_track_id)
    if not canvas_url:
        return None
    return await spotify_canvas_service.download_canvas_bytes(canvas_url)
