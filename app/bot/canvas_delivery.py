"""Entrega de Spotify Canvas com cache de file_id (compartilhado com /tstory).

Contrato Last-Step:
- 2 meios para obter a URL do vídeo (site público + oficial opcional)
- estados finais de ponta: CANVAS_HIT | PLAYING_FALLBACK
- legenda do Canvas == legenda do /playing

Fluxo:
1. Resolve track_id Last.fm ("lfm:<hash>") -> Spotify base62 quando preciso
   (track_id ORIGINAL preservado pro register_card/likes).
2. CACHE HIT de file_id -> reenvia vídeo (CANVAS_HIT).
3. MISS: resolve URL (2 meios) -> baixa bytes -> sobe/arquivo -> cache file_id
   -> envia vídeo (CANVAS_HIT).
4. Se ambos os meios falharem (ou download/send falhar): PLAYING_FALLBACK
   com a MESMA legenda do /playing (capa ou texto).
5. Em todo caminho: register_card + reação do bot no card.
"""
from __future__ import annotations

import html
import logging

from aiogram.types import BufferedInputFile, Message

from app.bot.telegram import _react_to_own_card
from app.config.settings import CANVAS_CACHE_CHANNEL_ID, CANVAS_CACHE_ENABLED
from app.services.canvas_audio import get_canvas_with_preview_asset
from app.services.canvas_cache import canvas_cache_service, is_cacheable_track_id
from app.services.canvas_processed_cache import canvas_processed_cache_service
from app.services.cover_cache import cover_cache_service
from app.services.reactions import reactions_service
from app.services.spotify import spotify_service
from app.services.spotify_canvas import spotify_canvas_service

logger = logging.getLogger(__name__)


def _extract_file_ids(sent: Message) -> tuple[str | None, str | None]:
    """Extrai (file_id, file_unique_id) de uma mensagem enviada.

    Canvas é mp4 vertical sem áudio: o Telegram normalmente devolve `.video`,
    mas pode classificar como `.animation` (mp4 sem som) ou, raramente, como
    `.document`. Tenta os três pra capturar o file_id em qualquer caso.
    """
    for attr in ("video", "animation", "document"):
        media = getattr(sent, attr, None)
        if media is not None:
            return media.file_id, getattr(media, "file_unique_id", None)
    return None, None


def _archive_caption(track: dict, canvas_track_id: str) -> str:
    """Legenda neutra pro canal de arquivo (sem emoji, HTML-escaped)."""
    name = str(track.get("track_name") or "").strip()
    artist = str(track.get("artist") or "").strip()
    if name and artist:
        return f"{html.escape(name)} — {html.escape(artist)}"
    if name:
        return html.escape(name)
    return html.escape(canvas_track_id)


async def _resolve_canvas_track_id(track: dict, track_id: str, log_prefix: str) -> str:
    """Resolve "lfm:<hash>" -> Spotify track_id base62 via Search API.

    Mantém o track_id ORIGINAL intacto no caller (chave histórica dos likes);
    devolve só o id usável pro Canvas (ou o próprio original se já é Spotify).
    """
    if not track_id.startswith("lfm:"):
        return track_id
    artist = str(track.get("artist") or "").strip()
    track_name = str(track.get("track_name") or "").strip()
    if not (artist and track_name):
        return track_id
    try:
        match = await spotify_service.search_track(artist, track_name)
        if match and match.get("id"):
            resolved = match["id"]
            logger.info(
                "%s_RESOLVED lfm=%s -> spotify=%s artist=%s track=%s",
                log_prefix, track_id, resolved, artist, track_name,
            )
            return resolved
        logger.info("%s_RESOLVE_MISS lfm=%s artist=%s track=%s", log_prefix, track_id, artist, track_name)
    except Exception:
        logger.exception("%s_RESOLVE_ERROR lfm=%s artist=%s track=%s", log_prefix, track_id, artist, track_name)
    return track_id


async def deliver_canvas(
    message: Message,
    *,
    track: dict,
    track_id: str,
    caption: str,
    cover: str | None,
    card_emoji: str | None,
    keyboard=None,
    log_prefix: str = "CANVAS",
) -> Message:
    """Entrega o Canvas (com cache file_id) ou cai no fallback. Sempre registra
    o card e reage. `track_id` é o ORIGINAL (likes); a resolução p/ Spotify é
    interna. `keyboard=None` no /tly (sem botões)."""
    user_id = message.from_user.id if message.from_user else 0
    bot = message.bot

    async def _finalize(sent: Message) -> Message:
        await reactions_service.register_card(
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            track_id=track_id,
            owner_user_id=user_id,
            track_name=str(track.get("track_name") or "").strip() or None,
            artist_name=str(track.get("artist") or "").strip() or None,
        )
        await _react_to_own_card(sent.bot, sent.chat.id, sent.message_id, card_emoji)
        return sent

    async def _fallback() -> Message:
        logger.info("%s_FINAL=PLAYING_FALLBACK track_id=%s", log_prefix, track_id)
        if cover:
            photo = await cover_cache_service.resolve_photo(
                bot,
                track_id=track_id,
                cover_url=cover,
                filename="canvas-fallback-cover.jpg",
            )
            try:
                sent = await message.answer_photo(photo=photo or cover, caption=caption, parse_mode="HTML", reply_markup=keyboard)
            except Exception:
                logger.warning("%s_FALLBACK_COVER_SEND_FAILED track_id=%s", log_prefix, track_id, exc_info=True)
                if photo and photo != cover:
                    await cover_cache_service.forget(track_id=track_id, cover_url=cover, photo=cover)
                    try:
                        sent = await message.answer_photo(photo=cover, caption=caption, parse_mode="HTML", reply_markup=keyboard)
                    except Exception:
                        sent = await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)
                else:
                    sent = await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)
        else:
            sent = await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)
        return await _finalize(sent)

    async def _send_by_file_id(file_id: str, *, audio_cache_key: str | None = None) -> Message | None:
        try:
            return await message.answer_video(
                video=file_id, caption=caption, parse_mode="HTML", reply_markup=keyboard
            )
        except Exception:
            logger.warning("%s_FILEID_SEND_FAILED track_id=%s", log_prefix, track_id, exc_info=True)
            if audio_cache_key:
                await canvas_processed_cache_service.forget(audio_cache_key)
            return None

    canvas_track_id = await _resolve_canvas_track_id(track, track_id, log_prefix)
    cache_on = CANVAS_CACHE_ENABLED and is_cacheable_track_id(canvas_track_id)

    # Camada opcional: Canvas com preview oficial. Atômica: se falhar em qualquer
    # etapa, retorna None e o fluxo bruto validado abaixo continua intacto.
    if cache_on:
        audio_asset = await get_canvas_with_preview_asset(
            bot, track=track, track_id=canvas_track_id, log_prefix=f"{log_prefix}_AUDIO", want_bytes=False
        )
        if audio_asset and audio_asset.file_id:
            sent = await _send_by_file_id(audio_asset.file_id, audio_cache_key=audio_asset.cache_key)
            if sent is not None:
                logger.info("%s_AUDIO_CACHE_HIT track_id=%s cache_key=%s", log_prefix, canvas_track_id, audio_asset.cache_key)
                logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=audio_cache", log_prefix, canvas_track_id)
                return await _finalize(sent)

    # CACHE HIT (fast path, sem lock): reenvia por file_id.
    if cache_on:
        cached = await canvas_cache_service.get_file_id(canvas_track_id)
        if cached:
            sent = await _send_by_file_id(cached)
            if sent is not None:
                logger.info("%s_CACHE_HIT track_id=%s", log_prefix, canvas_track_id)
                logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=file_id_cache", log_prefix, canvas_track_id)
                return await _finalize(sent)
            # file_id velho/inválido: esquece e segue pro miss (re-sobe).
            await canvas_cache_service.forget(canvas_track_id)

    if not cache_on:
        return await _deliver_uncached(
            message, canvas_track_id, caption, cover, keyboard, log_prefix,
            _finalize, _fallback,
        )

    # MISS sob lock por-track (coalesce 2 users pedindo a mesma faixa nova).
    async with canvas_cache_service.lock(canvas_track_id):
        cached = await canvas_cache_service.get_file_id(canvas_track_id)
        if cached:
            sent = await _send_by_file_id(cached)
            if sent is not None:
                logger.info("%s_CACHE_HIT_LOCKED track_id=%s", log_prefix, canvas_track_id)
                logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=file_id_cache_locked", log_prefix, canvas_track_id)
                return await _finalize(sent)
            await canvas_cache_service.forget(canvas_track_id)

        canvas_url = await spotify_canvas_service.get_canvas_url(canvas_track_id)
        if not canvas_url:
            logger.info("%s_NO_CANVAS track_id=%s", log_prefix, track_id)
            return await _fallback()

        canvas_bytes = await spotify_canvas_service.download_canvas_bytes(canvas_url)
        if not canvas_bytes:
            logger.info("%s_DOWNLOAD_FAILED track_id=%s", log_prefix, track_id)
            return await _fallback()

        filename = f"canvas-{canvas_track_id}.mp4"

        # Sobe UMA vez no canal de arquivo (se configurado) pra obter um file_id
        # reusável + manter o acervo. Depois o grupo recebe POR file_id (zero
        # upload). Sem canal, sobe direto no grupo e captura o file_id de lá.
        if CANVAS_CACHE_CHANNEL_ID:
            try:
                archived = await bot.send_video(
                    chat_id=CANVAS_CACHE_CHANNEL_ID,
                    video=BufferedInputFile(canvas_bytes, filename=filename),
                    caption=_archive_caption(track, canvas_track_id),
                    parse_mode="HTML",
                )
                fid, fuid = _extract_file_ids(archived)
                if fid:
                    await canvas_cache_service.put(canvas_track_id, fid, fuid)
                    logger.info("%s_ARCHIVED track_id=%s", log_prefix, canvas_track_id)
                    sent = await _send_by_file_id(fid)
                    if sent is not None:
                        logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=archive", log_prefix, canvas_track_id)
                        return await _finalize(sent)
                    # file_id do canal não serviu pro grupo (raríssimo): esquece
                    # e cai pro upload direto com os bytes que já temos.
                    await canvas_cache_service.forget(canvas_track_id)
            except Exception:
                logger.warning("%s_ARCHIVE_FAILED track_id=%s", log_prefix, canvas_track_id, exc_info=True)

        # Upload direto no grupo (sem canal, ou se o arquivo/canal falhou).
        try:
            sent = await message.answer_video(
                video=BufferedInputFile(canvas_bytes, filename=filename),
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("%s_SEND_FAILED track_id=%s", log_prefix, track_id)
            return await _fallback()

        fid, fuid = _extract_file_ids(sent)
        if fid:
            await canvas_cache_service.put(canvas_track_id, fid, fuid)
            logger.info("%s_CACHED_FROM_GROUP track_id=%s", log_prefix, canvas_track_id)
        logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=direct_upload", log_prefix, canvas_track_id)
        return await _finalize(sent)


async def _deliver_uncached(
    message, canvas_track_id, caption, cover, keyboard, log_prefix, _finalize, _fallback
) -> Message:
    """Caminho sem cache (cache desligado ou track_id não-Spotify): comportamento
    idêntico ao original — resolve URL, baixa e sobe os bytes no grupo."""
    canvas_url = await spotify_canvas_service.get_canvas_url(canvas_track_id)
    if not canvas_url:
        logger.info("%s_NO_CANVAS track_id=%s", log_prefix, canvas_track_id)
        return await _fallback()
    canvas_bytes = await spotify_canvas_service.download_canvas_bytes(canvas_url)
    if not canvas_bytes:
        logger.info("%s_DOWNLOAD_FAILED track_id=%s", log_prefix, canvas_track_id)
        return await _fallback()
    try:
        sent = await message.answer_video(
            video=BufferedInputFile(canvas_bytes, filename=f"canvas-{canvas_track_id}.mp4"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("%s_SEND_FAILED track_id=%s", log_prefix, canvas_track_id)
        return await _fallback()
    logger.info("%s_FINAL=CANVAS_HIT track_id=%s via=uncached", log_prefix, canvas_track_id)
    return await _finalize(sent)
