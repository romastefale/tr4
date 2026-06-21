from __future__ import annotations

import asyncio
import html
import io
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Document, Message

from app.config.settings import (
    LASTFM_SCROBBLE_IMPORT_MAX_EXPANDED_ITEMS,
    LASTFM_SCROBBLE_IMPORT_MAX_FILE_BYTES,
    LASTFM_SCROBBLE_IMPORT_MAX_PER_JOB,
    LASTFM_SCROBBLE_IMPORT_REQUIRE_CONFIRM,
    LASTFM_SCROBBLE_IMPORT_SEND_REMAINING_CSV,
    LASTFM_SCROBBLE_IMPORT_SEND_RETRY_CSV,
    LASTFM_SCROBBLE_IMPORT_STAGE_SIZE,
    LASTFM_SCROBBLE_IMPORT_STAGE_SLEEP_SECONDS,
    is_code_owner,
)
from app.services.lastfm_scrobbler import (
    FailedScrobble,
    ParsedScrobbleCsv,
    ScrobbleItem,
    build_count_csv,
    check_lastfm_auth,
    count_items,
    parse_scrobble_csv,
    scrobble_items,
)

logger = logging.getLogger(__name__)
router = Router(name="owner_lastfm_scrobble_import")

_COMMANDS = {"lfmimportcsv", "lfmscrobbles", "scrobblecsv"}
_COMMAND_RE = re.compile(r"^/(lfmimportcsv|lfmscrobbles|scrobblecsv)(?:@\w+)?(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class ImportOptions:
    confirmed: bool
    limit: int


def _command_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _is_import_caption(message: Message) -> bool:
    return bool(message.document and _COMMAND_RE.match(message.caption or ""))


def _parse_options(text: str) -> ImportOptions:
    # Remove command token and parse simple flags: confirm, limit=123, 123.
    parts = text.split()
    tokens = parts[1:] if parts and parts[0].startswith("/") else parts
    confirmed = any(token.lower() in {"confirm", "confirmar", "enviar", "send", "apply", "aplicar"} for token in tokens)
    limit = LASTFM_SCROBBLE_IMPORT_MAX_PER_JOB
    for token in tokens:
        lowered = token.lower().strip()
        match = re.fullmatch(r"(?:--)?limit(?:e)?[=:](\d+)", lowered)
        if match:
            limit = int(match.group(1))
            continue
        if lowered.isdigit():
            limit = int(lowered)
    # This is an anti-flood hard cap per Telegram command execution. For a larger
    # CSV, the bot returns a continuation CSV for the next run/day.
    limit = max(1, min(limit, LASTFM_SCROBBLE_IMPORT_MAX_PER_JOB))
    return ImportOptions(confirmed=confirmed, limit=limit)


def _document_from_message(message: Message) -> Document | None:
    if message.document:
        return message.document
    reply = message.reply_to_message
    if reply and reply.document:
        return reply.document
    return None


def _is_private_owner(message: Message) -> bool:
    return bool(message.from_user and message.chat.type == "private" and is_code_owner(message.from_user.id))


async def _download_document_bytes(message: Message, document: Document) -> bytes:
    if not message.bot:
        raise RuntimeError("Bot ausente no contexto da mensagem.")
    if document.file_size and document.file_size > LASTFM_SCROBBLE_IMPORT_MAX_FILE_BYTES:
        raise ValueError(
            f"Arquivo grande demais: {document.file_size} bytes. Limite: {LASTFM_SCROBBLE_IMPORT_MAX_FILE_BYTES} bytes."
        )
    filename = (document.file_name or "").lower()
    mime = (document.mime_type or "").lower()
    if filename and not filename.endswith(".csv") and "csv" not in mime and "text" not in mime:
        raise ValueError("Envie um arquivo .csv ou text/csv.")
    file = await message.bot.get_file(document.file_id)
    if not file.file_path:
        raise ValueError("Telegram não retornou file_path para baixar o CSV.")
    buffer = io.BytesIO()
    await message.bot.download_file(file.file_path, destination=buffer)
    data = buffer.getvalue()
    if len(data) > LASTFM_SCROBBLE_IMPORT_MAX_FILE_BYTES:
        raise ValueError(
            f"Arquivo grande demais após download: {len(data)} bytes. Limite: {LASTFM_SCROBBLE_IMPORT_MAX_FILE_BYTES} bytes."
        )
    return data


def _fmt_codes(codes: dict[str, int]) -> str:
    if not codes:
        return "nenhum"
    return ", ".join(f"{html.escape(str(code))}={count}" for code, count in sorted(codes.items()))


def _preview_text(parsed: ParsedScrobbleCsv, *, limit: int, confirmed: bool) -> str:
    action = "serão enviados" if confirmed else "seriam enviados"
    process_count = min(len(parsed.items), limit)
    remaining_count = max(0, len(parsed.items) - process_count)
    stage_size = max(1, LASTFM_SCROBBLE_IMPORT_STAGE_SIZE)
    lines = [
        "<b>Importação Last.fm CSV</b>",
        "",
        f"Linhas lidas: <code>{parsed.rows_read}</code>",
        f"Faixas únicas: <code>{parsed.unique_tracks}</code>",
        f"Scrobbles no CSV: <code>{len(parsed.items)}</code>",
        f"Nesta execução {action}: <code>{process_count}</code>",
        f"Tamanho de etapa: <code>{stage_size}</code>",
        f"Etapas previstas: <code>{math.ceil(process_count / stage_size) if process_count else 0}</code>",
    ]
    if remaining_count:
        lines.append(f"Ficarão para continuação: <code>{remaining_count}</code>")
    if parsed.rejected_rows:
        lines.append(f"Linhas ignoradas por erro: <code>{parsed.rejected_rows}</code>")
    lines.extend(["", "<b>Prévia por ordem do CSV:</b>"])
    for artist, track, count in parsed.aggregate_preview[:10]:
        lines.append(f"• <code>{count}</code> × {html.escape(artist)} — {html.escape(track)}")
    if not confirmed:
        lines.extend(
            [
                "",
                "Nada foi enviado. Para aplicar, envie o CSV com legenda:",
                "<code>/lfmimportcsv confirm</code>",
                "ou responda ao CSV com:",
                "<code>/lfmimportcsv confirm limit=500</code>",
            ]
        )
    return "\n".join(lines)


def _stage_text(
    *,
    source_name: str,
    stage_index: int,
    stage_total: int,
    requested: int,
    accepted: int,
    ignored: int,
    failed_count: int,
    ignored_codes: dict[str, int],
    api_errors: list[str],
    daily_limit_hit: bool,
    rate_limit_hit: bool,
) -> str:
    status = "concluída" if not api_errors and ignored == 0 and not daily_limit_hit and not rate_limit_hit else "concluída com aviso"
    lines = [
        f"<b>Etapa {stage_index}/{stage_total} {status}</b>",
        f"Arquivo: <code>{html.escape(source_name or 'csv')}</code>",
        f"Solicitados na etapa: <code>{requested}</code>",
        f"Aceitos pelo Last.fm: <code>{accepted}</code>",
        f"Ignorados pelo Last.fm: <code>{ignored}</code>",
        f"Falhas para retry: <code>{failed_count}</code>",
    ]
    if ignored_codes:
        lines.append(f"Códigos ignorados: <code>{_fmt_codes(ignored_codes)}</code>")
    if daily_limit_hit:
        lines.append("Limite diário sinalizado pelo Last.fm. A importação foi parada para não afogar a API.")
    if rate_limit_hit:
        lines.append("Rate limit da API sinalizado pelo Last.fm. A importação foi parada para evitar insistência indevida.")
    if api_errors:
        lines.append("Erros/API:")
        for err in api_errors[:3]:
            lines.append(f"• <code>{html.escape(str(err)[:350])}</code>")
    return "\n".join(lines)



def _auth_check_text(result) -> str:
    lines = [
        "<b>Diagnóstico Last.fm API</b>",
        f"API key fingerprint: <code>{html.escape(result.api_key_fingerprint)}</code>",
        f"Shared secret length: <code>{result.secret_length}</code>",
        f"Session key length: <code>{result.session_key_length}</code>",
    ]
    if result.ok:
        lines.extend(
            [
                "Status: <b>OK</b>",
                f"Conta autenticada: <code>{html.escape(result.username or '')}</code>",
                f"Subscriber/Pro flag: <code>{html.escape(result.subscriber or '')}</code>",
                f"Playcount: <code>{html.escape(result.playcount or '')}</code>",
            ]
        )
    else:
        lines.extend(
            [
                "Status: <b>FALHA</b>",
                f"Código Last.fm: <code>{html.escape(result.error_code or '')}</code>",
                f"Mensagem: <code>{html.escape(result.message or '')}</code>",
            ]
        )
        if result.error_code == "13":
            lines.append("Fato: erro 13 = assinatura inválida. Verifique se TR3_LASTFM_API_KEY e TR3_LASTFM_API_SECRET são do mesmo API account e se o secret não foi colado com aspas/espaços.")
        elif result.error_code == "9":
            lines.append("Fato: erro 9 = session key inválida. Gere novamente a TR3_LASTFM_SESSION_KEY usando a mesma API key/secret configurada no Railway.")
    return "\n".join(lines)

def _filename(prefix: str, source_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name or "csv").strip("_") or "csv"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{safe}.csv"


async def _send_count_csv(message: Message, *, items: list[ScrobbleItem], filename: str, caption: str) -> None:
    if not items:
        return
    data = build_count_csv(items)
    await message.answer_document(BufferedInputFile(data, filename=filename), caption=caption)


async def _run_job(
    message: Message,
    items: list[ScrobbleItem],
    *,
    remaining_after_limit: list[ScrobbleItem],
    source_name: str,
) -> None:
    stage_size = max(1, LASTFM_SCROBBLE_IMPORT_STAGE_SIZE)
    stage_total = max(1, math.ceil(len(items) / stage_size))
    accepted_total = 0
    ignored_total = 0
    requested_total = 0
    failed: list[FailedScrobble] = []
    final_remaining = list(remaining_after_limit)
    stopped_early = False
    stopped_reason = ""

    await message.answer(
        "<b>Importação Last.fm iniciada</b>\n"
        f"Total desta execução: <code>{len(items)}</code>\n"
        f"Etapas: <code>{stage_total}</code> × até <code>{stage_size}</code> scrobbles."
    )

    try:
        for stage_index, offset in enumerate(range(0, len(items), stage_size), start=1):
            stage_items = items[offset : offset + stage_size]
            result = await scrobble_items(stage_items)
            requested_total += result.requested
            accepted_total += result.accepted
            ignored_total += result.ignored
            failed.extend(result.failed_items)

            await message.answer(
                _stage_text(
                    source_name=source_name,
                    stage_index=stage_index,
                    stage_total=stage_total,
                    requested=result.requested,
                    accepted=result.accepted,
                    ignored=result.ignored,
                    failed_count=len(result.failed_items) + len(result.unprocessed_items),
                    ignored_codes=result.ignored_codes,
                    api_errors=result.api_errors,
                    daily_limit_hit=result.daily_limit_hit,
                    rate_limit_hit=result.rate_limit_hit,
                )
            )

            if result.stopped_early:
                stopped_early = True
                if result.daily_limit_hit:
                    stopped_reason = "A execução parou porque o Last.fm sinalizou limite diário."
                elif result.rate_limit_hit:
                    stopped_reason = "A execução parou porque o Last.fm sinalizou rate limit."
                elif result.api_errors:
                    stopped_reason = "A execução parou por erro de API/credencial. O lote atual foi isolado para retry."
                else:
                    stopped_reason = "A execução parou antes do fim. O restante foi isolado para continuação."
                final_remaining = result.unprocessed_items + items[offset + len(stage_items) :] + final_remaining
                break

            if LASTFM_SCROBBLE_IMPORT_STAGE_SLEEP_SECONDS > 0 and offset + stage_size < len(items):
                await asyncio.sleep(LASTFM_SCROBBLE_IMPORT_STAGE_SLEEP_SECONDS)

        lines = [
            "<b>Importação Last.fm finalizada</b>",
            "",
            f"Arquivo: <code>{html.escape(source_name or 'csv')}</code>",
            f"Solicitados nesta execução: <code>{requested_total}</code>",
            f"Aceitos pelo Last.fm: <code>{accepted_total}</code>",
            f"Ignorados pelo Last.fm: <code>{ignored_total}</code>",
            f"Falhas isoladas para retry: <code>{len(failed)}</code>",
            f"Restante não processado: <code>{len(final_remaining)}</code>",
        ]
        if stopped_early and stopped_reason:
            lines.append(stopped_reason)
        await message.answer("\n".join(lines))

        failed_items = [failure.item for failure in failed]
        if failed_items and LASTFM_SCROBBLE_IMPORT_SEND_RETRY_CSV:
            await _send_count_csv(
                message,
                items=failed_items,
                filename=_filename("lastfm_retry_failed", source_name),
                caption="CSV isolado com músicas que falharam/foram ignoradas. Use este arquivo depois para tentar novamente.",
            )
        if final_remaining and LASTFM_SCROBBLE_IMPORT_SEND_REMAINING_CSV:
            await _send_count_csv(
                message,
                items=final_remaining,
                filename=_filename("lastfm_remaining", source_name),
                caption="CSV de continuação com o restante que não foi processado nesta execução.",
            )
    except Exception as exc:
        logger.exception("LASTFM_SCROBBLE_IMPORT_JOB_FAILED")
        await message.answer(f"Importação falhou: <code>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</code>")
        pending = items[requested_total:] + final_remaining
        if pending and LASTFM_SCROBBLE_IMPORT_SEND_RETRY_CSV:
            await _send_count_csv(
                message,
                items=pending,
                filename=_filename("lastfm_retry_after_crash", source_name),
                caption="CSV gerado após erro geral. Confira antes de reenviar para evitar duplicidade.",
            )


async def _handle_import_message(message: Message) -> None:
    if not _is_private_owner(message):
        if message.chat.type == "private":
            await message.answer("Comando exclusivo do owner e somente na DM do bot.")
        return

    options = _parse_options(_command_text(message))
    document = _document_from_message(message)
    if not document:
        await message.answer(
            "Envie um CSV na DM com legenda <code>/lfmimportcsv</code> para prévia, "
            "ou <code>/lfmimportcsv confirm</code> para aplicar. Também pode responder ao CSV com o comando."
        )
        return

    try:
        data = await _download_document_bytes(message, document)
        parsed = parse_scrobble_csv(data, max_expanded_items=LASTFM_SCROBBLE_IMPORT_MAX_EXPANDED_ITEMS)
    except Exception as exc:
        await message.answer(f"Não consegui ler o CSV: <code>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</code>")
        return

    if LASTFM_SCROBBLE_IMPORT_REQUIRE_CONFIRM and not options.confirmed:
        await message.answer(_preview_text(parsed, limit=options.limit, confirmed=False))
        return

    selected = parsed.items[: options.limit]
    remaining = parsed.items[options.limit :]
    await message.answer(_preview_text(parsed, limit=options.limit, confirmed=True) + "\n\nProcessando em segundo plano.")
    asyncio.create_task(_run_job(message, selected, remaining_after_limit=remaining, source_name=document.file_name or "csv"))


@router.message(Command("lfmcheckauth", "lastfmcheckauth"))
async def lastfm_check_auth_command(message: Message) -> None:
    if not _is_private_owner(message):
        if message.chat.type == "private":
            await message.answer("Comando exclusivo do owner e somente na DM do bot.")
        return
    try:
        result = await check_lastfm_auth()
    except Exception as exc:
        logger.exception("LASTFM_AUTH_CHECK_FAILED")
        await message.answer(f"Diagnóstico Last.fm falhou: <code>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</code>")
        return
    await message.answer(_auth_check_text(result))


@router.message(Command(*_COMMANDS))
async def lastfm_import_csv_command(message: Message) -> None:
    await _handle_import_message(message)


@router.message(F.document)
async def lastfm_import_csv_caption(message: Message):
    if not _is_import_caption(message):
        return UNHANDLED
    await _handle_import_message(message)
