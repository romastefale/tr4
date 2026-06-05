from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref, public_tme_url, safe_public_username
from app.equalizador.mesa import ensure_phase5_tables

logger = logging.getLogger(__name__)

DDX_HARD_MODE = "hard"
DDX_SOFT_MODE = "soft"
DDX_SOFT_DELAY_SECONDS = 10 * 60
DDX_MAX_WORDS = 250
DDX_MAX_WORD_LEN = 80
DDX_MAX_TEXT_LEN = 4096
_SCHEDULED_TASKS: dict[str, asyncio.Task[None]] = {}
_SCHEDULED_BOUND = 1000


class DDXError(RuntimeError):
    """Raised when DDX configuration or runtime action fails."""


class DDXNotFoundError(DDXError):
    """Raised when a public DDX reference is unknown."""


@dataclass(frozen=True)
class _DDXSnapshot:
    scheduled_ref: str
    event_ref: str
    chat_id: int
    message_id: int
    palco_ref: str
    chat_title: str
    actor_name: str
    actor_username: str | None
    text_value: str
    matched_words: tuple[str, ...]
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = re.sub(r"\s+", " ", str(value or "").strip())
    return text_value[:240] or fallback


def _safe_summary(value: object, *, limit: int = 160) -> str:
    text_value = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "…"


def _normalize_spaced(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").lower())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_compact(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").lower())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", value)


def _parse_words(raw: object) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, (list, tuple, set)):
        items = [str(item) for item in raw]
    else:
        items = re.split(r"[,;\n]", str(raw or ""))
    for item in items:
        word = re.sub(r"\s+", " ", str(item or "").strip().lower())
        if not word:
            continue
        word = word[:DDX_MAX_WORD_LEN]
        key = _normalize_spaced(word)
        if not key or key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= DDX_MAX_WORDS:
            break
    return words


def _load_words(raw_json: object) -> list[str]:
    try:
        data = json.loads(str(raw_json or "[]"))
    except Exception:
        return []
    return _parse_words(data if isinstance(data, list) else [])


def _matching_words(text_value: str, words: list[str]) -> list[str]:
    spaced_text = _normalize_spaced(text_value)
    compact_text = _normalize_compact(text_value)
    matches: list[str] = []
    for word in words:
        original_word = str(word).strip()
        spaced_word = _normalize_spaced(original_word)
        compact_word = _normalize_compact(original_word)
        if not spaced_word or not compact_word:
            continue
        if " " in spaced_word and spaced_word in spaced_text:
            matches.append(original_word)
        elif " " not in spaced_word and (spaced_word in spaced_text or compact_word in compact_text):
            matches.append(original_word)
        if len(matches) >= 5:
            break
    return matches


def _mode_label(mode: str) -> str:
    return "DDX 10 minutos" if mode == DDX_SOFT_MODE else "DDX imediato"


def _filter_ref(*, palco_ref: str, mode: str, alias_secret: str) -> str:
    seed = f"ddx-filter:{palco_ref}:{mode}"
    return "ddx_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _event_ref(*, palco_ref: str, mode: str, message_id: int, created_at: str, alias_secret: str) -> str:
    seed = f"ddx-event:{palco_ref}:{mode}:{message_id}:{created_at}"
    return "ddxev_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _scheduled_ref(*, palco_ref: str, message_id: int, created_at: str, alias_secret: str) -> str:
    seed = f"ddx-soft:{palco_ref}:{message_id}:{created_at}"
    return "ddx10_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def ensure_ddx_tables(db_engine: Engine = default_engine) -> None:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_ddx_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    words_json TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 0,
                    updated_by_ref TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_chat_id, mode)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_ddx_filters_palco ON eq_ddx_filters(palco_ref, mode)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_ddx_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    scheduled_ref TEXT,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor_name TEXT,
                    actor_username TEXT,
                    matched_words_json TEXT NOT NULL DEFAULT '[]',
                    text_preview TEXT,
                    public_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_ddx_events_palco ON eq_ddx_events(palco_ref, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_ddx_events_sched ON eq_ddx_events(scheduled_ref, status)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_ddx_soft_pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_ref TEXT NOT NULL UNIQUE,
                    event_ref TEXT NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    due_at TEXT NOT NULL,
                    actor_name TEXT,
                    actor_username TEXT,
                    matched_words_json TEXT NOT NULL DEFAULT '[]',
                    text_preview TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_ddx_soft_pending_palco ON eq_ddx_soft_pending(palco_ref, status, due_at)"))


def salvar_ddx_config(
    *,
    palco: dict[str, object],
    ator_ref: str,
    mode: str,
    words: object,
    enabled: bool,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    if mode not in {DDX_HARD_MODE, DDX_SOFT_MODE}:
        raise DDXError("modo_ddx_invalido")
    safe_words = _parse_words(words)
    now = _now_iso()
    palco_ref = str(palco.get("ui_ref") or "")
    chat_id = int(palco["telegram_chat_id"])
    filter_ref = _filter_ref(palco_ref=palco_ref, mode=mode, alias_secret=alias_secret)
    ensure_ddx_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_ddx_filters (filter_ref, telegram_chat_id, palco_ref, mode, words_json, enabled, updated_by_ref, updated_at)
                VALUES (:filter_ref, :chat_id, :palco_ref, :mode, :words_json, :enabled, :ator_ref, :now)
                ON CONFLICT(telegram_chat_id, mode) DO UPDATE SET
                    filter_ref=excluded.filter_ref,
                    palco_ref=excluded.palco_ref,
                    words_json=excluded.words_json,
                    enabled=excluded.enabled,
                    updated_by_ref=excluded.updated_by_ref,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "filter_ref": filter_ref,
                "chat_id": chat_id,
                "palco_ref": palco_ref,
                "mode": mode,
                "words_json": json.dumps(safe_words, ensure_ascii=False),
                "enabled": 1 if enabled else 0,
                "ator_ref": str(ator_ref),
                "now": now,
            },
        )
    return _filter_public(
        {
            "filter_ref": filter_ref,
            "palco_ref": palco_ref,
            "mode": mode,
            "words_json": json.dumps(safe_words, ensure_ascii=False),
            "enabled": 1 if enabled else 0,
            "updated_at": now,
        }
    )


def _filter_public(row: dict[str, Any]) -> dict[str, object]:
    mode = str(row.get("mode") or DDX_HARD_MODE)
    words = _load_words(row.get("words_json"))
    return {
        "filter_ref": str(row.get("filter_ref") or ""),
        "modo": mode,
        "nome": _mode_label(mode),
        "enabled": bool(row.get("enabled")),
        "palavras": words,
        "total_palavras": len(words),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _event_public(row: dict[str, Any]) -> dict[str, object]:
    username = safe_public_username(row.get("actor_username"))
    return {
        "event_ref": str(row.get("event_ref") or ""),
        "scheduled_ref": str(row.get("scheduled_ref") or "") if row.get("scheduled_ref") else None,
        "modo": str(row.get("mode") or DDX_HARD_MODE),
        "nome": _mode_label(str(row.get("mode") or DDX_HARD_MODE)),
        "status": str(row.get("status") or "registrado"),
        "autor_nome": _safe_text(row.get("actor_name"), fallback="Membro"),
        "autor_username": username,
        "autor_url": public_tme_url(username),
        "palavras": _load_words(row.get("matched_words_json")),
        "preview": _safe_summary(row.get("text_preview"), limit=180),
        "detalhe": _safe_text(row.get("public_detail"), fallback=""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _pending_public(row: dict[str, Any]) -> dict[str, object]:
    username = safe_public_username(row.get("actor_username"))
    return {
        "scheduled_ref": str(row.get("scheduled_ref") or ""),
        "event_ref": str(row.get("event_ref") or ""),
        "status": str(row.get("status") or "pending"),
        "autor_nome": _safe_text(row.get("actor_name"), fallback="Membro"),
        "autor_username": username,
        "autor_url": public_tme_url(username),
        "palavras": _load_words(row.get("matched_words_json")),
        "preview": _safe_summary(row.get("text_preview"), limit=180),
        "due_at": str(row.get("due_at") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def list_ddx_publico(*, palco: dict[str, object], alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_ddx_tables(db_engine)
    chat_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco.get("ui_ref") or "")
    default_rows = {
        DDX_HARD_MODE: {
            "filter_ref": _filter_ref(palco_ref=palco_ref, mode=DDX_HARD_MODE, alias_secret=alias_secret),
            "palco_ref": palco_ref,
            "mode": DDX_HARD_MODE,
            "words_json": "[]",
            "enabled": 0,
            "updated_at": "",
        },
        DDX_SOFT_MODE: {
            "filter_ref": _filter_ref(palco_ref=palco_ref, mode=DDX_SOFT_MODE, alias_secret=alias_secret),
            "palco_ref": palco_ref,
            "mode": DDX_SOFT_MODE,
            "words_json": "[]",
            "enabled": 0,
            "updated_at": "",
        },
    }
    with db_engine.begin() as conn:
        filters = conn.execute(
            text("SELECT * FROM eq_ddx_filters WHERE telegram_chat_id=:chat_id ORDER BY mode ASC"),
            {"chat_id": chat_id},
        ).mappings().all()
        events = conn.execute(
            text(
                """
                SELECT * FROM eq_ddx_events
                WHERE telegram_chat_id=:chat_id
                ORDER BY created_at DESC, id DESC
                LIMIT 30
                """
            ),
            {"chat_id": chat_id},
        ).mappings().all()
        pending = conn.execute(
            text(
                """
                SELECT * FROM eq_ddx_soft_pending
                WHERE telegram_chat_id=:chat_id AND status='pending'
                ORDER BY due_at ASC, id ASC
                LIMIT 30
                """
            ),
            {"chat_id": chat_id},
        ).mappings().all()
    merged = {**default_rows}
    for row in filters:
        merged[str(row.get("mode") or DDX_HARD_MODE)] = dict(row)
    return {
        "filtros": [_filter_public(merged[DDX_HARD_MODE]), _filter_public(merged[DDX_SOFT_MODE])],
        "eventos": [_event_public(dict(row)) for row in events],
        "pendentes": [_pending_public(dict(row)) for row in pending],
        "resumo": {
            "imediato_ativo": bool(_filter_public(merged[DDX_HARD_MODE])["enabled"]),
            "temporario_ativo": bool(_filter_public(merged[DDX_SOFT_MODE])["enabled"]),
            "pendentes": len(pending),
        },
    }


def cancelar_ddx_agendado(
    *,
    palco: dict[str, object],
    scheduled_ref: str,
    ator_ref: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_ddx_tables(db_engine)
    chat_id = int(palco["telegram_chat_id"])
    safe_ref = str(scheduled_ref or "").strip()
    if not safe_ref.startswith("ddx10_"):
        raise DDXNotFoundError("referencia_indisponivel")
    now = _now_iso()
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM eq_ddx_soft_pending WHERE telegram_chat_id=:chat_id AND scheduled_ref=:ref"),
            {"chat_id": chat_id, "ref": safe_ref},
        ).mappings().first()
        if not row:
            raise DDXNotFoundError("referencia_indisponivel")
        if str(row.get("status") or "") != "pending":
            return {"ok": True, "scheduled_ref": safe_ref, "status": str(row.get("status") or "finalizado"), "resumo": "Agendamento já finalizado."}
        conn.execute(
            text("UPDATE eq_ddx_soft_pending SET status='canceled', updated_at=:now WHERE scheduled_ref=:ref"),
            {"now": now, "ref": safe_ref},
        )
        conn.execute(
            text(
                """
                UPDATE eq_ddx_events
                SET status='canceled', public_detail='Cancelado por governante.', updated_at=:now
                WHERE scheduled_ref=:ref
                """
            ),
            {"now": now, "ref": safe_ref},
        )
    task = _SCHEDULED_TASKS.pop(safe_ref, None)
    if task and not task.done():
        task.cancel()
    return {"ok": True, "scheduled_ref": safe_ref, "status": "canceled", "resumo": "Apagamento DDX 10 minutos cancelado."}


def _record_event(
    *,
    event_ref: str,
    scheduled_ref: str | None,
    chat_id: int,
    palco_ref: str,
    mode: str,
    status: str,
    actor_name: str,
    actor_username: str | None,
    matched_words: list[str] | tuple[str, ...],
    text_preview: str,
    public_detail: str,
    db_engine: Engine = default_engine,
) -> None:
    now = _now_iso()
    ensure_ddx_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO eq_ddx_events
                (event_ref, scheduled_ref, telegram_chat_id, palco_ref, mode, status, actor_name, actor_username,
                 matched_words_json, text_preview, public_detail, created_at, updated_at)
                VALUES (:event_ref, :scheduled_ref, :chat_id, :palco_ref, :mode, :status, :actor_name, :actor_username,
                        :matched_words, :preview, :detail,
                        COALESCE((SELECT created_at FROM eq_ddx_events WHERE event_ref=:event_ref), :now), :now)
                """
            ),
            {
                "event_ref": event_ref,
                "scheduled_ref": scheduled_ref,
                "chat_id": chat_id,
                "palco_ref": palco_ref,
                "mode": mode,
                "status": status,
                "actor_name": _safe_text(actor_name, fallback="Membro"),
                "actor_username": safe_public_username(actor_username),
                "matched_words": json.dumps(list(matched_words), ensure_ascii=False),
                "preview": _safe_summary(text_preview, limit=400),
                "detail": _safe_text(public_detail, fallback=""),
                "now": now,
            },
        )


def _get_filter_for_chat(chat_id: int, mode: str, *, db_engine: Engine = default_engine) -> dict[str, Any] | None:
    ensure_ddx_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM eq_ddx_filters WHERE telegram_chat_id=:chat_id AND mode=:mode"),
            {"chat_id": int(chat_id), "mode": str(mode)},
        ).mappings().first()
    return dict(row) if row else None


def _palco_ref_for_chat(chat_id: int, *, alias_secret: str, db_engine: Engine = default_engine) -> str:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT ui_ref FROM eq_palcos WHERE telegram_chat_id=:chat_id LIMIT 1"),
            {"chat_id": int(chat_id)},
        ).mappings().first()
    if row and row.get("ui_ref"):
        return str(row["ui_ref"])
    return make_ui_ref("grp", int(chat_id), alias_secret)


async def _notify_maestros(bot: Any, text: str) -> None:
    targets = sorted({int(v) for v in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET if int(v) != 0})[:5]
    if not targets:
        return
    for user_id in targets:
        try:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.debug("DDX_NOTIFY_FAILED", exc_info=True)


def _message_text(message: Any) -> str:
    return str(getattr(message, "text", None) or getattr(message, "caption", None) or "")[:DDX_MAX_TEXT_LEN]


def _is_group_message(message: Any) -> bool:
    chat = getattr(message, "chat", None)
    chat_type = str(getattr(chat, "type", "") or "").lower()
    return "group" in chat_type


def _actor_public(message: Any) -> tuple[str, str | None]:
    user = getattr(message, "from_user", None)
    if not user:
        return "Membro", None
    return _safe_text(getattr(user, "full_name", None), fallback="Membro"), safe_public_username(getattr(user, "username", None))


async def _delete_soft_after_delay(bot: Any, snap: _DDXSnapshot, delay_seconds: int = DDX_SOFT_DELAY_SECONDS) -> None:
    try:
        await asyncio.sleep(max(1, int(delay_seconds)))
        ensure_ddx_tables()
        with default_engine.begin() as conn:
            row = conn.execute(
                text("SELECT status FROM eq_ddx_soft_pending WHERE scheduled_ref=:ref"),
                {"ref": snap.scheduled_ref},
            ).mappings().first()
            if not row or str(row.get("status") or "") != "pending":
                return
        try:
            await bot.delete_message(chat_id=snap.chat_id, message_id=snap.message_id)
            status = "deleted"
            detail = "Mensagem apagada após 10 minutos."
        except Exception as exc:
            status = "failed"
            detail = "Telegram recusou o apagamento agendado."
            logger.debug("DDX_SOFT_DELETE_FAILED", exc_info=True)
        now = _now_iso()
        with default_engine.begin() as conn:
            conn.execute(
                text("UPDATE eq_ddx_soft_pending SET status=:status, updated_at=:now WHERE scheduled_ref=:ref"),
                {"status": status, "now": now, "ref": snap.scheduled_ref},
            )
        _record_event(
            event_ref=snap.event_ref,
            scheduled_ref=snap.scheduled_ref,
            chat_id=snap.chat_id,
            palco_ref=snap.palco_ref,
            mode=DDX_SOFT_MODE,
            status=status,
            actor_name=snap.actor_name,
            actor_username=snap.actor_username,
            matched_words=snap.matched_words,
            text_preview=snap.text_value,
            public_detail=detail,
        )
        if status == "deleted":
            words = ", ".join(html.escape(w) for w in snap.matched_words) or "filtro"
            await _notify_maestros(
                bot,
                "Equalizador · DDX 10 minutos\n\n"
                f"Grupo: {html.escape(snap.chat_title)}\n"
                f"Autor: {html.escape(snap.actor_name)}{(' · @' + html.escape(snap.actor_username)) if snap.actor_username else ''}\n"
                f"Filtro: {words}\n\n"
                f"Mensagem apagada após 10 minutos:\n<blockquote>{html.escape(_safe_summary(snap.text_value, limit=900))}</blockquote>",
            )
    except asyncio.CancelledError:
        raise
    finally:
        _SCHEDULED_TASKS.pop(snap.scheduled_ref, None)


async def equalizador_ddx_preprocess_update(bot: Any, update: Any, *, alias_secret: str | None = None) -> bool:
    """Run DDX immediate and 10-minute rules for group messages.

    Returns True only when the immediate DDX deleted the message and the update
    should not continue to regular bot handlers. The 10-minute DDX never consumes
    the update; it schedules a delayed deletion and returns False.
    """
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    if not message or not _is_group_message(message):
        return False
    text_value = _message_text(message)
    if not text_value:
        return False
    chat = getattr(message, "chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    message_id = int(getattr(message, "message_id", 0) or 0)
    if not chat_id or not message_id:
        return False
    secret = alias_secret or settings.equalizador_alias_secret()
    palco_ref = _palco_ref_for_chat(chat_id, alias_secret=secret)
    actor_name, actor_username = _actor_public(message)
    chat_title = _safe_text(getattr(chat, "title", None), fallback="Grupo")

    hard = _get_filter_for_chat(chat_id, DDX_HARD_MODE)
    if hard and bool(hard.get("enabled")):
        words = _load_words(hard.get("words_json"))
        matches = _matching_words(text_value, words)
        if matches:
            created_at = _now_iso()
            event_ref = _event_ref(palco_ref=palco_ref, mode=DDX_HARD_MODE, message_id=message_id, created_at=created_at, alias_secret=secret)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                status = "deleted"
                detail = "Mensagem apagada imediatamente."
                logger.warning("EQUALIZADOR_DDX_HARD_DELETED | palco=%s | event=%s", palco_ref, event_ref)
            except Exception:
                status = "failed"
                detail = "Telegram recusou o apagamento imediato."
                logger.debug("EQUALIZADOR_DDX_HARD_FAILED", exc_info=True)
            _record_event(
                event_ref=event_ref,
                scheduled_ref=None,
                chat_id=chat_id,
                palco_ref=palco_ref,
                mode=DDX_HARD_MODE,
                status=status,
                actor_name=actor_name,
                actor_username=actor_username,
                matched_words=matches,
                text_preview=text_value,
                public_detail=detail,
            )
            if status == "deleted":
                words_text = ", ".join(html.escape(w) for w in matches) or "filtro"
                await _notify_maestros(
                    bot,
                    "Equalizador · DDX imediato\n\n"
                    f"Grupo: {html.escape(chat_title)}\n"
                    f"Autor: {html.escape(actor_name)}{(' · @' + html.escape(actor_username)) if actor_username else ''}\n"
                    f"Filtro: {words_text}\n\n"
                    f"Mensagem apagada:\n<blockquote>{html.escape(_safe_summary(text_value, limit=900))}</blockquote>",
                )
                return True
            return False

    soft = _get_filter_for_chat(chat_id, DDX_SOFT_MODE)
    if soft and bool(soft.get("enabled")):
        words = _load_words(soft.get("words_json"))
        matches = _matching_words(text_value, words)
        if matches and len(_SCHEDULED_TASKS) < _SCHEDULED_BOUND:
            created_at = _now_iso()
            event_ref = _event_ref(palco_ref=palco_ref, mode=DDX_SOFT_MODE, message_id=message_id, created_at=created_at, alias_secret=secret)
            sched_ref = _scheduled_ref(palco_ref=palco_ref, message_id=message_id, created_at=created_at, alias_secret=secret)
            snap = _DDXSnapshot(
                scheduled_ref=sched_ref,
                event_ref=event_ref,
                chat_id=chat_id,
                message_id=message_id,
                palco_ref=palco_ref,
                chat_title=chat_title,
                actor_name=actor_name,
                actor_username=actor_username,
                text_value=text_value,
                matched_words=tuple(matches),
                created_at=created_at,
            )
            due_at = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + DDX_SOFT_DELAY_SECONDS, tz=timezone.utc).isoformat()
            ensure_ddx_tables()
            with default_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO eq_ddx_soft_pending
                        (scheduled_ref, event_ref, telegram_chat_id, palco_ref, telegram_message_id, status, due_at,
                         actor_name, actor_username, matched_words_json, text_preview, created_at, updated_at)
                        VALUES (:scheduled_ref, :event_ref, :chat_id, :palco_ref, :message_id, 'pending', :due_at,
                                :actor_name, :actor_username, :matched_words, :preview, :now, :now)
                        """
                    ),
                    {
                        "scheduled_ref": sched_ref,
                        "event_ref": event_ref,
                        "chat_id": chat_id,
                        "palco_ref": palco_ref,
                        "message_id": message_id,
                        "due_at": due_at,
                        "actor_name": actor_name,
                        "actor_username": actor_username,
                        "matched_words": json.dumps(matches, ensure_ascii=False),
                        "preview": _safe_summary(text_value, limit=400),
                        "now": created_at,
                    },
                )
            _record_event(
                event_ref=event_ref,
                scheduled_ref=sched_ref,
                chat_id=chat_id,
                palco_ref=palco_ref,
                mode=DDX_SOFT_MODE,
                status="scheduled",
                actor_name=actor_name,
                actor_username=actor_username,
                matched_words=matches,
                text_preview=text_value,
                public_detail="Apagamento programado para 10 minutos.",
            )
            task = asyncio.create_task(_delete_soft_after_delay(bot, snap), name=f"ddx_soft:{sched_ref}")
            _SCHEDULED_TASKS[sched_ref] = task
            logger.info("EQUALIZADOR_DDX_SOFT_SCHEDULED | palco=%s | event=%s", palco_ref, event_ref)
    return False


def ddx_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, DDXNotFoundError):
        return "Agendamento DDX indisponível."
    return "Ajuste DDX não concluído."
