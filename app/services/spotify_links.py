from __future__ import annotations

import re
from urllib.parse import urlparse

_SPOTIFY_TRACK_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
_SPOTIFY_URI_RE = re.compile(r"(?i)\bspotify:track:([A-Za-z0-9]{22})\b")
_URL_RE = re.compile(r"(?i)https?://[^\s<>'\"]+")
_ALLOWED_SHORT_HOSTS = {"spotify.link", "www.spotify.link", "spotify.app.link", "www.spotify.app.link"}
_ALLOWED_OPEN_HOSTS = {"open.spotify.com", "www.open.spotify.com"}


def _clean_candidate(value: str | None) -> str:
    return str(value or "").strip().strip("<>[](){}.,;!?'\"")


def _valid_track_id(value: str | None) -> str | None:
    candidate = _clean_candidate(value)
    return candidate if _SPOTIFY_TRACK_ID_RE.fullmatch(candidate) else None


def _track_id_from_open_spotify_url(value: str | None) -> str | None:
    raw = _clean_candidate(value)
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.netloc or "").casefold()
    if host not in _ALLOWED_OPEN_HOSTS:
        return None
    parts = [part for part in (parsed.path or "").split("/") if part]
    for idx, part in enumerate(parts):
        if part.casefold() == "track" and idx + 1 < len(parts):
            return _valid_track_id(parts[idx + 1])
    return None


def extract_spotify_track_id(value: str | None) -> str | None:
    """Extrai ID de faixa Spotify de URI ou URL pública do Spotify.

    Suporta os formatos oficiais documentados pela Spotify:
    - spotify:track:{id}
    - https://open.spotify.com/track/{id}

    Também aceita variantes com prefixo regional no path, como
    /intl-pt/track/{id}, porque o marcador semântico continua sendo
    o segmento "track" seguido pelo ID base-62 de 22 caracteres.
    """
    text = str(value or "").strip()
    if not text:
        return None
    uri_match = _SPOTIFY_URI_RE.search(text)
    if uri_match:
        return uri_match.group(1)
    direct = _track_id_from_open_spotify_url(text)
    if direct:
        return direct
    for match in _URL_RE.finditer(text):
        direct = _track_id_from_open_spotify_url(match.group(0))
        if direct:
            return direct
    return None


def first_spotify_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for match in _URL_RE.finditer(text):
        url = _clean_candidate(match.group(0))
        try:
            parsed = urlparse(url)
        except Exception:
            continue
        host = (parsed.netloc or "").casefold()
        if host in _ALLOWED_OPEN_HOSTS or host in _ALLOWED_SHORT_HOSTS:
            return url
    return None


def is_allowed_spotify_short_url(value: str | None) -> bool:
    url = first_spotify_url(value)
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return (parsed.netloc or "").casefold() in _ALLOWED_SHORT_HOSTS


def looks_like_spotify_track_reference(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if extract_spotify_track_id(text):
        return True
    return is_allowed_spotify_short_url(text)
