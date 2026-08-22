from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx

from app.config.settings import (
    DATA_DIR,
    HTTP_TIMEOUT_SECONDS,
    LASTFM_API_BASE_URL,
    LASTFM_API_KEY,
    LASTFM_API_SECRET,
    LASTFM_SCROBBLE_IMPORT_BATCH_SIZE,
    LASTFM_SCROBBLE_IMPORT_SLEEP_SECONDS,
    LASTFM_SCROBBLE_IMPORT_SPACING_SECONDS,
    LASTFM_SCROBBLE_IMPORT_STOP_ON_DAILY_LIMIT,
    LASTFM_SESSION_KEY,
)

logger = logging.getLogger(__name__)

LASTFM_SCROBBLE_METHOD = "track.scrobble"
LASTFM_MAX_SCROBBLES_PER_REQUEST = 50
# Last.fm rejects timestamps too far in the past. Keep generated timestamps
# comfortably inside a recent window instead of trying to backfill history.
LASTFM_MAX_SAFE_BACKDATE_SECONDS = 13 * 24 * 60 * 60


@dataclass(frozen=True)
class ScrobbleItem:
    artist: str
    track: str
    album: str | None = None


@dataclass(frozen=True)
class FailedScrobble:
    item: ScrobbleItem
    reason_code: str
    reason_text: str


@dataclass(frozen=True)
class ScrobbleImportResult:
    requested: int
    accepted: int
    ignored: int
    ignored_codes: dict[str, int]
    api_errors: list[str]
    failed_items: list[FailedScrobble]
    unprocessed_items: list[ScrobbleItem]
    daily_limit_hit: bool
    rate_limit_hit: bool
    stopped_early: bool


@dataclass(frozen=True)
class LastfmAuthCheckResult:
    ok: bool
    username: str | None
    subscriber: str | None
    playcount: str | None
    error_code: str | None
    message: str | None
    api_key_fingerprint: str
    secret_length: int
    session_key_length: int


def build_api_sig(params: dict[str, str], api_secret: str) -> str:
    """Build Last.fm API signature.

    Last.fm requires ASCII-sorted parameter names, excluding format/callback.
    """
    material = ""
    for key in sorted(k for k in params if k not in {"format", "callback"}):
        material += f"{key}{params[key]}"
    material += api_secret
    return hashlib.md5(material.encode("utf-8")).hexdigest()


_SESSION_FILE = DATA_DIR / "lastfm_session.json"


def get_lastfm_session_key() -> str:
    stored = load_persisted_session()
    if stored and stored.get("sk"):
        return str(stored["sk"])
    return str(LASTFM_SESSION_KEY or "").strip()


def load_persisted_session() -> dict[str, str] | None:
    try:
        payload = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    sk = str(payload.get("sk") or "").strip()
    if not sk:
        return None
    return {
        "sk": sk,
        "username": str(payload.get("username") or "").strip(),
    }


def save_persisted_session(*, sk: str, username: str = "") -> bool:
    try:
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_FILE.write_text(
            json.dumps({"sk": sk, "username": username}, ensure_ascii=True),
            encoding="utf-8",
        )
        return True
    except OSError:
        logger.exception("LASTFM_SESSION_PERSIST_FAILED path=%s", _SESSION_FILE)
        return False


def _signing_config_error() -> str | None:
    missing = []
    if not LASTFM_API_KEY:
        missing.append("TR3_LASTFM_API_KEY")
    if not LASTFM_API_SECRET:
        missing.append("TR3_LASTFM_API_SECRET")
    if missing:
        return "Variáveis ausentes: " + ", ".join(missing)
    return None


def _config_error() -> str | None:
    signing = _signing_config_error()
    if signing:
        return signing
    if not get_lastfm_session_key():
        return "Last.fm ainda não autorizado. Use /lfmauth no privado."
    return None


async def _signed_post(params: dict[str, str]) -> dict[str, Any]:
    payload = dict(params)
    payload["api_sig"] = build_api_sig(payload, str(LASTFM_API_SECRET))
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(LASTFM_API_BASE_URL, data=payload)
    try:
        body = response.json()
    except Exception:
        body = {"error": f"http_{response.status_code}", "message": response.text[:500]}
    if not isinstance(body, dict):
        return {"error": "malformed_response", "message": str(body)[:300]}
    if response.status_code != 200 and "error" not in body:
        body["error"] = f"http_{response.status_code}"
    return body


async def lastfm_get_auth_token() -> tuple[str | None, str | None]:
    error = _signing_config_error()
    if error:
        return None, error
    body = await _signed_post(
        {
            "method": "auth.getToken",
            "api_key": str(LASTFM_API_KEY),
            "format": "json",
        }
    )
    token = str(body.get("token") or "").strip()
    if token:
        return token, None
    return None, str(body.get("message") or body.get("error") or "Não consegui gerar o token Last.fm.")


def lastfm_auth_url(token: str) -> str:
    return f"https://www.last.fm/api/auth/?api_key={LASTFM_API_KEY}&token={token}"


async def lastfm_get_session(token: str) -> tuple[str | None, str | None, str | None]:
    error = _signing_config_error()
    if error:
        return None, None, error
    body = await _signed_post(
        {
            "method": "auth.getSession",
            "api_key": str(LASTFM_API_KEY),
            "token": token,
            "format": "json",
        }
    )
    session = body.get("session") if isinstance(body.get("session"), dict) else {}
    sk = str(session.get("key") or "").strip()
    username = str(session.get("name") or "").strip()
    if sk:
        return sk, username, None
    return None, None, str(body.get("message") or body.get("error") or "Autorize no Last.fm e toque de novo em Já autorizei.")


def _fingerprint(value: str) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _lastfm_credential_facts() -> tuple[str, int, int]:
    return (
        _fingerprint(str(LASTFM_API_KEY or "")),
        len(str(LASTFM_API_SECRET or "")),
        len(str(get_lastfm_session_key() or "")),
    )


async def check_lastfm_auth() -> LastfmAuthCheckResult:
    api_key_fp, secret_len, sk_len = _lastfm_credential_facts()
    config_error = _config_error()
    if config_error:
        return LastfmAuthCheckResult(
            ok=False,
            username=None,
            subscriber=None,
            playcount=None,
            error_code="config",
            message=config_error,
            api_key_fingerprint=api_key_fp,
            secret_length=secret_len,
            session_key_length=sk_len,
        )

    params: dict[str, str] = {
        "method": "user.getInfo",
        "api_key": str(LASTFM_API_KEY),
        "sk": str(get_lastfm_session_key()),
        "format": "json",
    }
    params["api_sig"] = build_api_sig(params, str(LASTFM_API_SECRET))

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(LASTFM_API_BASE_URL, data=params)
    try:
        payload = response.json()
    except Exception:
        payload = {"message": response.text[:500], "error": f"http_{response.status_code}"}

    if response.status_code != 200 or (isinstance(payload, dict) and payload.get("error")):
        return LastfmAuthCheckResult(
            ok=False,
            username=None,
            subscriber=None,
            playcount=None,
            error_code=str(payload.get("error") if isinstance(payload, dict) else f"http_{response.status_code}"),
            message=str(payload.get("message") if isinstance(payload, dict) else payload),
            api_key_fingerprint=api_key_fp,
            secret_length=secret_len,
            session_key_length=sk_len,
        )

    user = payload.get("user", {}) if isinstance(payload, dict) else {}
    return LastfmAuthCheckResult(
        ok=True,
        username=str(user.get("name") or ""),
        subscriber=str(user.get("subscriber") or ""),
        playcount=str(user.get("playcount") or ""),
        error_code=None,
        message=None,
        api_key_fingerprint=api_key_fp,
        secret_length=secret_len,
        session_key_length=sk_len,
    )

def _safe_batch_size(value: int) -> int:
    if value < 1:
        return 1
    return min(value, LASTFM_MAX_SCROBBLES_PER_REQUEST)


def _timestamps_for(total: int, spacing_seconds: int) -> list[int]:
    now = int(time.time())
    if total <= 0:
        return []
    spacing = max(1, int(spacing_seconds or 1))
    max_spacing = max(1, (LASTFM_MAX_SAFE_BACKDATE_SECONDS - 300) // max(total, 1))
    spacing = min(spacing, max_spacing)
    start = now - (total * spacing) - 60
    return [start + (idx * spacing) for idx in range(total)]


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ignored_message_from(scrobble: dict[str, Any]) -> tuple[str, str]:
    ignored_message = scrobble.get("ignoredMessage") or scrobble.get("ignoredmessage") or {}
    if isinstance(ignored_message, dict):
        code = str(ignored_message.get("code") or "0")
        text = str(ignored_message.get("#text") or ignored_message.get("text") or "")
        return code, text
    return "0", ""


def _parse_scrobble_response(
    payload: dict[str, Any], submitted_items: list[ScrobbleItem]
) -> tuple[int, int, Counter[str], list[FailedScrobble], bool]:
    scrobbles = payload.get("scrobbles") if isinstance(payload, dict) else None
    if not isinstance(scrobbles, dict):
        return 0, 0, Counter({"malformed_response": 1}), [
            FailedScrobble(item=item, reason_code="malformed_response", reason_text="Resposta Last.fm malformada")
            for item in submitted_items
        ], False

    attr = scrobbles.get("@attr") or scrobbles.get("attr") or {}
    try:
        accepted = int(attr.get("accepted", 0))
    except Exception:
        accepted = 0
    try:
        ignored = int(attr.get("ignored", 0))
    except Exception:
        ignored = 0

    ignored_codes: Counter[str] = Counter()
    failed_items: list[FailedScrobble] = []
    daily_limit_hit = False
    response_items = _listify(scrobbles.get("scrobble"))
    for idx, response_item in enumerate(response_items):
        if idx >= len(submitted_items) or not isinstance(response_item, dict):
            continue
        code, text = _ignored_message_from(response_item)
        if code and code != "0":
            ignored_codes[code] += 1
            if code == "5":
                daily_limit_hit = True
            failed_items.append(FailedScrobble(item=submitted_items[idx], reason_code=code, reason_text=text))

    # Fallback: if Last.fm reports ignored items but did not return per-item details,
    # keep the trailing rows as retry candidates to avoid silent loss.
    if ignored > len(failed_items):
        missing = ignored - len(failed_items)
        for item in submitted_items[-missing:]:
            failed_items.append(FailedScrobble(item=item, reason_code="unknown_ignored", reason_text="Ignorado sem detalhe"))
        ignored_codes["unknown_ignored"] += missing

    return accepted, ignored, ignored_codes, failed_items, daily_limit_hit


async def scrobble_items(items: list[ScrobbleItem]) -> ScrobbleImportResult:
    config_error = _config_error()
    if config_error:
        return ScrobbleImportResult(
            requested=len(items),
            accepted=0,
            ignored=0,
            ignored_codes={},
            api_errors=[config_error],
            failed_items=[FailedScrobble(item=item, reason_code="config", reason_text=config_error) for item in items],
            unprocessed_items=[],
            daily_limit_hit=False,
            rate_limit_hit=False,
            stopped_early=True,
        )

    batch_size = _safe_batch_size(LASTFM_SCROBBLE_IMPORT_BATCH_SIZE)
    timestamps = _timestamps_for(len(items), LASTFM_SCROBBLE_IMPORT_SPACING_SECONDS)
    accepted_total = 0
    ignored_total = 0
    ignored_codes: Counter[str] = Counter()
    api_errors: list[str] = []
    failed_items: list[FailedScrobble] = []
    unprocessed_items: list[ScrobbleItem] = []
    daily_limit_hit = False
    rate_limit_hit = False
    stopped_early = False

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for offset in range(0, len(items), batch_size):
            batch = items[offset : offset + batch_size]
            params: dict[str, str] = {
                "method": LASTFM_SCROBBLE_METHOD,
                "api_key": str(LASTFM_API_KEY),
                "sk": str(get_lastfm_session_key()),
                "format": "json",
            }
            for idx, item in enumerate(batch):
                absolute_idx = offset + idx
                params[f"artist[{idx}]"] = item.artist
                params[f"track[{idx}]"] = item.track
                params[f"timestamp[{idx}]"] = str(timestamps[absolute_idx])
                if item.album:
                    params[f"album[{idx}]"] = item.album
            params["api_sig"] = build_api_sig(params, str(LASTFM_API_SECRET))

            try:
                response = await client.post(LASTFM_API_BASE_URL, data=params)
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text[:500]}
                if response.status_code != 200:
                    error_code = str(payload.get("error") or f"http_{response.status_code}") if isinstance(payload, dict) else f"http_{response.status_code}"
                    error = f"HTTP {response.status_code}: {payload}"
                    api_errors.append(error)
                    rate_limited = response.status_code == 429 or error_code == "29"
                    if rate_limited:
                        rate_limit_hit = True
                        error_code = "rate_limit"
                    # Request-level failures are not per-track validation results. Stop here
                    # and preserve the current batch plus remaining rows for retry/continuation.
                    stopped_early = True
                    failed_items.extend(
                        FailedScrobble(item=item, reason_code=error_code, reason_text=error)
                        for item in batch
                    )
                    unprocessed_items = items[offset + len(batch) :]
                    break
                if isinstance(payload, dict) and payload.get("error"):
                    error_code = str(payload.get("error") or "api_error")
                    error = f"Last.fm erro {payload.get('error')}: {payload.get('message')}"
                    api_errors.append(error)
                    if error_code == "29":
                        rate_limit_hit = True
                        error_code = "rate_limit"
                    # Request-level API errors usually affect the whole request or credentials.
                    # Stop instead of repeating the same bad request across the whole CSV.
                    stopped_early = True
                    failed_items.extend(
                        FailedScrobble(item=item, reason_code=error_code, reason_text=error)
                        for item in batch
                    )
                    unprocessed_items = items[offset + len(batch) :]
                    break
                accepted, ignored, batch_codes, batch_failed, batch_daily_limit = _parse_scrobble_response(
                    payload if isinstance(payload, dict) else {}, batch
                )
                accepted_total += accepted
                ignored_total += ignored
                ignored_codes.update(batch_codes)
                failed_items.extend(batch_failed)
                if batch_daily_limit:
                    daily_limit_hit = True
                    if LASTFM_SCROBBLE_IMPORT_STOP_ON_DAILY_LIMIT:
                        stopped_early = True
                        unprocessed_items = items[offset + len(batch) :]
                        break
            except Exception as exc:
                logger.exception("LASTFM_SCROBBLE_IMPORT_BATCH_FAILED offset=%s size=%s", offset, len(batch))
                error = f"{type(exc).__name__}: {exc}"
                api_errors.append(error)
                failed_items.extend(
                    FailedScrobble(item=item, reason_code="client_exception", reason_text=error) for item in batch
                )
                stopped_early = True
                unprocessed_items = items[offset + len(batch) :]
                break

            if LASTFM_SCROBBLE_IMPORT_SLEEP_SECONDS > 0 and offset + batch_size < len(items):
                import asyncio

                await asyncio.sleep(LASTFM_SCROBBLE_IMPORT_SLEEP_SECONDS)

    return ScrobbleImportResult(
        requested=len(items),
        accepted=accepted_total,
        ignored=ignored_total,
        ignored_codes=dict(ignored_codes),
        api_errors=api_errors[:20],
        failed_items=failed_items,
        unprocessed_items=unprocessed_items,
        daily_limit_hit=daily_limit_hit,
        rate_limit_hit=rate_limit_hit,
        stopped_early=stopped_early,
    )
