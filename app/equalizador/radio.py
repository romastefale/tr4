from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import (
    MesaError,
    MesaTelegramError,
    ensure_bot_right,
    record_historico,
    register_mensagem_ref,
    _safe_text,
)
from app.equalizador.erros_telegram import telegram_error_info_from_payload


class RadioError(RuntimeError):
    """Raised when a Radio draft/publication cannot be completed."""


class RadioNotFoundError(RadioError):
    """Raised when a public Radio draft reference is unknown."""


class RadioMediaError(RadioError):
    """Raised when a media draft is invalid or too large."""


MAX_TEXT_LEN = 4096
MAX_CAPTION_LEN = 1024
MAX_MEDIA_BYTES = 8 * 1024 * 1024
ALLOWED_MEDIA_KINDS = {"photo", "video", "document"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def radio_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, RadioNotFoundError):
        return "Rascunho indisponível."
    if isinstance(exc, RadioMediaError):
        return _safe_text(exc, fallback="Mídia inválida.")
    if isinstance(exc, MesaTelegramError):
        return _safe_text(exc.description, fallback="Telegram recusou a publicação.")
    if isinstance(exc, MesaError):
        return _safe_text(exc, fallback="Publicação não concluída.")
    return "Publicação não concluída."


def _sqlite_column_exists(conn: Any, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    return any(str(row.get("name")) == column for row in rows)


def ensure_radio_tables(db_engine: Engine = default_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    ator_ref TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    texto TEXT,
                    media_kind TEXT,
                    media_filename TEXT,
                    media_mime TEXT,
                    media_base64 TEXT,
                    sem_preview INTEGER NOT NULL DEFAULT 1,
                    sem_notificacao INTEGER NOT NULL DEFAULT 0,
                    fixar INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'draft',
                    msg_ref TEXT,
                    resumo_publico TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        for column, ddl in (
            ("media_kind", "ALTER TABLE eq_radio_drafts ADD COLUMN media_kind TEXT"),
            ("media_filename", "ALTER TABLE eq_radio_drafts ADD COLUMN media_filename TEXT"),
            ("media_mime", "ALTER TABLE eq_radio_drafts ADD COLUMN media_mime TEXT"),
            ("media_base64", "ALTER TABLE eq_radio_drafts ADD COLUMN media_base64 TEXT"),
            ("sem_preview", "ALTER TABLE eq_radio_drafts ADD COLUMN sem_preview INTEGER NOT NULL DEFAULT 1"),
            ("sem_notificacao", "ALTER TABLE eq_radio_drafts ADD COLUMN sem_notificacao INTEGER NOT NULL DEFAULT 0"),
            ("fixar", "ALTER TABLE eq_radio_drafts ADD COLUMN fixar INTEGER NOT NULL DEFAULT 0"),
            ("msg_ref", "ALTER TABLE eq_radio_drafts ADD COLUMN msg_ref TEXT"),
        ):
            if not _sqlite_column_exists(conn, "eq_radio_drafts", column):
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_drafts_palco ON eq_radio_drafts(palco_ref, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_drafts_ref ON eq_radio_drafts(draft_ref)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    ator_ref TEXT NOT NULL,
                    nome TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    sem_preview INTEGER NOT NULL DEFAULT 1,
                    sem_notificacao INTEGER NOT NULL DEFAULT 0,
                    fixar INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_templates_palco ON eq_radio_templates(palco_ref, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_templates_ref ON eq_radio_templates(template_ref)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    ator_ref TEXT NOT NULL,
                    draft_ref TEXT,
                    msg_ref TEXT,
                    tipo TEXT NOT NULL,
                    resumo_publico TEXT NOT NULL,
                    media_kind TEXT,
                    fixar INTEGER NOT NULL DEFAULT 0,
                    fixado INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_history_palco ON eq_radio_history(palco_ref, created_at)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    ator_ref TEXT NOT NULL,
                    template_ref TEXT,
                    texto TEXT NOT NULL,
                    sem_preview INTEGER NOT NULL DEFAULT 1,
                    sem_notificacao INTEGER NOT NULL DEFAULT 0,
                    fixar INTEGER NOT NULL DEFAULT 0,
                    respeitar_silencio INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    scheduled_for TEXT NOT NULL,
                    last_error TEXT,
                    msg_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_schedules_due ON eq_radio_schedules(status, scheduled_for)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_radio_schedules_palco ON eq_radio_schedules(palco_ref, status, scheduled_for)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_quiet_policies (
                    palco_ref TEXT PRIMARY KEY,
                    telegram_chat_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    start_hhmm TEXT NOT NULL DEFAULT '22:00',
                    end_hhmm TEXT NOT NULL DEFAULT '08:00',
                    timezone_name TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
                    updated_by_ref TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_radio_broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broadcast_ref TEXT NOT NULL UNIQUE,
                    ator_ref TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    total_alvos INTEGER NOT NULL DEFAULT 0,
                    enviados INTEGER NOT NULL DEFAULT 0,
                    pulados INTEGER NOT NULL DEFAULT 0,
                    falhas INTEGER NOT NULL DEFAULT 0,
                    resumo_publico TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )


def _draft_ref(*, palco_ref: str, ator_ref: str, created_at: str, alias_secret: str) -> str:
    seed = f"radio:{palco_ref}:{ator_ref}:{created_at}"
    return "rad_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _template_ref(*, palco_ref: str, ator_ref: str, nome: str, created_at: str, alias_secret: str) -> str:
    seed = f"radio_template:{palco_ref}:{ator_ref}:{nome}:{created_at}"
    return "tpl_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _history_ref(*, palco_ref: str, msg_ref: str, created_at: str, alias_secret: str) -> str:
    seed = f"radio_history:{palco_ref}:{msg_ref}:{created_at}"
    return "rhi_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _media_from_payload(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None, int]:
    kind = str(payload.get("media_kind") or "").strip().lower()
    data_url = str(payload.get("media_base64") or "").strip()
    filename = _safe_text(payload.get("media_filename"), fallback="arquivo")[:120]
    mime = _safe_text(payload.get("media_mime"), fallback="application/octet-stream")[:120]
    if not data_url and not kind:
        return None, None, None, None, 0
    if kind not in ALLOWED_MEDIA_KINDS:
        raise RadioMediaError("Tipo de mídia indisponível. Use foto, vídeo ou documento.")
    if not data_url:
        raise RadioMediaError("Arquivo de mídia não recebido.")
    if "," in data_url and data_url.lower().startswith("data:"):
        header, raw_b64 = data_url.split(",", 1)
        match = re.match(r"data:([^;]+);base64", header, flags=re.I)
        if match:
            mime = match.group(1)[:120]
    else:
        raw_b64 = data_url
    try:
        decoded = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise RadioMediaError("Arquivo de mídia inválido.") from exc
    size = len(decoded)
    if size <= 0:
        raise RadioMediaError("Arquivo de mídia vazio.")
    if size > MAX_MEDIA_BYTES:
        raise RadioMediaError("Arquivo acima do limite seguro do painel: 8 MB.")
    # Store normalized base64 only, without data URL header.
    return kind, filename, mime, base64.b64encode(decoded).decode("ascii"), size


def public_radio_template_row(row: dict[str, Any]) -> dict[str, object]:
    texto = str(row.get("texto") or "")
    return {
        "template_ref": str(row.get("template_ref") or ""),
        "nome": _safe_text(row.get("nome"), fallback="Modelo Radio"),
        "previa": texto[:220],
        "sem_preview": bool(row.get("sem_preview")),
        "sem_notificacao": bool(row.get("sem_notificacao")),
        "fixar": bool(row.get("fixar")),
        "status": str(row.get("status") or "active"),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def criar_template_radio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    nome = _safe_text(payload.get("nome"), fallback="").strip()[:80]
    texto = str(payload.get("texto") or "").strip()
    if not nome:
        raise RadioError("Informe um nome para o modelo.")
    if not texto:
        raise RadioError("Escreva o texto do modelo.")
    if len(texto) > MAX_TEXT_LEN:
        raise RadioError("Texto do modelo acima do limite.")
    created_at = _now_iso()
    palco_ref = str(palco["ui_ref"])
    template_ref = _template_ref(palco_ref=palco_ref, ator_ref=ator_ref, nome=nome, created_at=created_at, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_radio_templates (
                    template_ref, telegram_chat_id, palco_ref, ator_ref, nome, texto,
                    sem_preview, sem_notificacao, fixar, status, created_at, updated_at
                ) VALUES (
                    :template_ref, :telegram_chat_id, :palco_ref, :ator_ref, :nome, :texto,
                    :sem_preview, :sem_notificacao, :fixar, 'active', :created_at, :updated_at
                )
                """
            ),
            {
                "template_ref": template_ref,
                "telegram_chat_id": int(palco["telegram_chat_id"]),
                "palco_ref": palco_ref,
                "ator_ref": ator_ref,
                "nome": nome,
                "texto": texto,
                "sem_preview": 1 if bool(payload.get("sem_preview", True)) else 0,
                "sem_notificacao": 1 if bool(payload.get("sem_notificacao", False)) else 0,
                "fixar": 1 if bool(payload.get("fixar", False)) else 0,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
    return public_radio_template_row(
        {
            "template_ref": template_ref,
            "nome": nome,
            "texto": texto,
            "sem_preview": 1 if bool(payload.get("sem_preview", True)) else 0,
            "sem_notificacao": 1 if bool(payload.get("sem_notificacao", False)) else 0,
            "fixar": 1 if bool(payload.get("fixar", False)) else 0,
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
        }
    )


def list_radio_templates_publicos(*, palco_ref: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT template_ref, nome, texto, sem_preview, sem_notificacao, fixar, status, created_at, updated_at
                FROM eq_radio_templates
                WHERE palco_ref=:palco_ref AND status='active'
                ORDER BY updated_at DESC, id DESC
                LIMIT 50
                """
            ),
            {"palco_ref": str(palco_ref)},
        ).mappings().all()
    return [public_radio_template_row(dict(row)) for row in rows]


def _get_template(*, palco_ref: str, template_ref: str, db_engine: Engine) -> dict[str, Any]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM eq_radio_templates
                WHERE palco_ref=:palco_ref AND template_ref=:template_ref AND status='active'
                LIMIT 1
                """
            ),
            {"palco_ref": str(palco_ref), "template_ref": str(template_ref)},
        ).mappings().first()
    if not row:
        raise RadioNotFoundError("modelo_indisponivel")
    return dict(row)


def criar_rascunho_de_template_radio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    template_ref: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    palco_ref = str(palco["ui_ref"])
    template = _get_template(palco_ref=palco_ref, template_ref=template_ref, db_engine=db_engine)
    return criar_rascunho_radio(
        palco=palco,
        ator_ref=ator_ref,
        payload={
            "texto": str(template.get("texto") or ""),
            "sem_preview": bool(template.get("sem_preview")),
            "sem_notificacao": bool(template.get("sem_notificacao")),
            "fixar": bool(template.get("fixar")),
        },
        alias_secret=alias_secret,
        db_engine=db_engine,
    )


def apagar_template_radio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    template_ref: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    palco_ref = str(palco["ui_ref"])
    template = _get_template(palco_ref=palco_ref, template_ref=template_ref, db_engine=db_engine)
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_radio_templates
                SET status='deleted', updated_at=:updated_at
                WHERE palco_ref=:palco_ref AND template_ref=:template_ref
                """
            ),
            {"updated_at": now, "palco_ref": palco_ref, "template_ref": template_ref},
        )
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=palco_ref,
        alvo_ref=str(template_ref),
        ajuste="radio.template.apagar",
        status="ok",
        resumo_publico=f"Modelo Radio apagado: {_safe_text(template.get('nome'), fallback='modelo')}",
        payload_tecnico={},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    template["status"] = "deleted"
    template["updated_at"] = now
    return {"ok": True, "template": public_radio_template_row(template), "historico": historico}


def criar_rascunho_radio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    texto = str(payload.get("texto") or "").strip()
    media_kind, media_filename, media_mime, media_base64, media_size = _media_from_payload(payload)
    tipo = "media" if media_kind else "text"
    limit = MAX_CAPTION_LEN if media_kind else MAX_TEXT_LEN
    if not texto and not media_kind:
        raise RadioError("Escreva um texto ou anexe uma mídia.")
    if len(texto) > limit:
        raise RadioError("Texto acima do limite da publicação.")
    created_at = _now_iso()
    palco_ref = str(palco["ui_ref"])
    draft_ref = _draft_ref(palco_ref=palco_ref, ator_ref=ator_ref, created_at=created_at, alias_secret=alias_secret)
    resumo = _safe_text(texto.replace("\n", " "), fallback=("Mídia para publicação" if media_kind else "Texto para publicação"))[:120]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_radio_drafts (
                    draft_ref, telegram_chat_id, palco_ref, ator_ref, tipo, texto, media_kind, media_filename,
                    media_mime, media_base64, sem_preview, sem_notificacao, fixar, status, resumo_publico,
                    created_at, updated_at
                ) VALUES (
                    :draft_ref, :telegram_chat_id, :palco_ref, :ator_ref, :tipo, :texto, :media_kind, :media_filename,
                    :media_mime, :media_base64, :sem_preview, :sem_notificacao, :fixar, 'draft', :resumo_publico,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "draft_ref": draft_ref,
                "telegram_chat_id": int(palco["telegram_chat_id"]),
                "palco_ref": palco_ref,
                "ator_ref": ator_ref,
                "tipo": tipo,
                "texto": texto or None,
                "media_kind": media_kind,
                "media_filename": media_filename,
                "media_mime": media_mime,
                "media_base64": media_base64,
                "sem_preview": 1 if bool(payload.get("sem_preview", True)) else 0,
                "sem_notificacao": 1 if bool(payload.get("sem_notificacao", False)) else 0,
                "fixar": 1 if bool(payload.get("fixar", False)) else 0,
                "resumo_publico": resumo,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
    return public_radio_draft_row(
        {
            "draft_ref": draft_ref,
            "tipo": tipo,
            "texto": texto,
            "media_kind": media_kind,
            "media_filename": media_filename,
            "media_mime": media_mime,
            "sem_preview": 1 if bool(payload.get("sem_preview", True)) else 0,
            "sem_notificacao": 1 if bool(payload.get("sem_notificacao", False)) else 0,
            "fixar": 1 if bool(payload.get("fixar", False)) else 0,
            "status": "draft",
            "msg_ref": None,
            "resumo_publico": resumo,
            "created_at": created_at,
            "updated_at": created_at,
            "media_size": media_size,
        }
    )


def public_radio_draft_row(row: dict[str, Any]) -> dict[str, object]:
    texto = str(row.get("texto") or "")
    previa = texto[:280]
    return {
        "draft_ref": str(row.get("draft_ref") or ""),
        "tipo": str(row.get("tipo") or "text"),
        "media_kind": str(row.get("media_kind") or ""),
        "media_filename": _safe_text(row.get("media_filename"), fallback="") or "",
        "media_mime": _safe_text(row.get("media_mime"), fallback="") or "",
        "resumo": _safe_text(row.get("resumo_publico"), fallback="Rascunho"),
        "previa": previa,
        "sem_preview": bool(row.get("sem_preview")),
        "sem_notificacao": bool(row.get("sem_notificacao")),
        "fixar": bool(row.get("fixar")),
        "status": str(row.get("status") or "draft"),
        "msg_ref": str(row.get("msg_ref") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def list_radio_drafts_publicos(*, palco_ref: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT draft_ref, tipo, texto, media_kind, media_filename, media_mime, sem_preview,
                       sem_notificacao, fixar, status, msg_ref, resumo_publico, created_at, updated_at
                FROM eq_radio_drafts
                WHERE palco_ref=:palco_ref
                ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'published' THEN 1 ELSE 2 END, updated_at DESC, id DESC
                LIMIT 30
                """
            ),
            {"palco_ref": str(palco_ref)},
        ).mappings().all()
    return [public_radio_draft_row(dict(row)) for row in rows]


def _get_draft(*, palco_ref: str, draft_ref: str, db_engine: Engine) -> dict[str, Any]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM eq_radio_drafts
                WHERE palco_ref=:palco_ref AND draft_ref=:draft_ref
                LIMIT 1
                """
            ),
            {"palco_ref": str(palco_ref), "draft_ref": str(draft_ref)},
        ).mappings().first()
    if not row:
        raise RadioNotFoundError("rascunho_indisponivel")
    return dict(row)


async def _telegram_json_call(bot_token: str, method: str, payload: dict[str, Any]) -> Any:
    if not bot_token:
        raise MesaError("token_indisponivel")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"https://api.telegram.org/bot{bot_token}/{method}", json=payload)
    try:
        data = response.json()
    except ValueError as exc:
        raise MesaError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        info = telegram_error_info_from_payload(data=data, status_code=response.status_code)
        raise MesaTelegramError(info.public_detail, error_info=info)
    return data.get("result")


async def _telegram_upload_call(bot_token: str, method: str, payload: dict[str, Any], *, field_name: str, file_bytes: bytes, filename: str, mime: str) -> Any:
    if not bot_token:
        raise MesaError("token_indisponivel")
    async with httpx.AsyncClient(timeout=35.0) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            data={key: ("true" if value is True else "false" if value is False else str(value)) for key, value in payload.items() if value is not None},
            files={field_name: (filename or "arquivo", file_bytes, mime or "application/octet-stream")},
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise MesaError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        info = telegram_error_info_from_payload(data=data, status_code=response.status_code)
        raise MesaTelegramError(info.public_detail, error_info=info)
    return data.get("result")


def _method_for_media(kind: str) -> tuple[str, str, str]:
    if kind == "photo":
        return "sendPhoto", "photo", "can_send_photos"
    if kind == "video":
        return "sendVideo", "video", "can_send_videos"
    return "sendDocument", "document", "can_send_documents"


def public_radio_history_row(row: dict[str, Any]) -> dict[str, object]:
    return {
        "event_ref": str(row.get("event_ref") or ""),
        "draft_ref": str(row.get("draft_ref") or ""),
        "msg_ref": str(row.get("msg_ref") or ""),
        "tipo": str(row.get("tipo") or "text"),
        "resumo": _safe_text(row.get("resumo_publico"), fallback="Publicação Radio"),
        "media_kind": str(row.get("media_kind") or ""),
        "fixar": bool(row.get("fixar")),
        "fixado": bool(row.get("fixado")),
        "created_at": str(row.get("created_at") or ""),
    }


def list_radio_history_publico(*, palco_ref: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_ref, draft_ref, msg_ref, tipo, resumo_publico, media_kind, fixar, fixado, created_at
                FROM eq_radio_history
                WHERE palco_ref=:palco_ref
                ORDER BY created_at DESC, id DESC
                LIMIT 50
                """
            ),
            {"palco_ref": str(palco_ref)},
        ).mappings().all()
    return [public_radio_history_row(dict(row)) for row in rows]


async def publicar_rascunho_radio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    draft_ref: str,
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    palco_ref = str(palco["ui_ref"])
    palco_id = int(palco["telegram_chat_id"])
    draft = _get_draft(palco_ref=palco_ref, draft_ref=draft_ref, db_engine=db_engine)
    if str(draft.get("status")) != "draft":
        raise RadioError("Rascunho já publicado ou cancelado.")
    texto = str(draft.get("texto") or "")
    media_kind = str(draft.get("media_kind") or "")
    await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right=None)
    if media_kind:
        method, field_name, required_right = _method_for_media(media_kind)
        await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right=required_right)
        raw_b64 = str(draft.get("media_base64") or "")
        try:
            file_bytes = base64.b64decode(raw_b64, validate=True)
        except Exception as exc:
            raise RadioMediaError("Mídia do rascunho não pôde ser lida.") from exc
        payload: dict[str, Any] = {
            "chat_id": palco_id,
            "caption": texto[:MAX_CAPTION_LEN] if texto else None,
            "disable_notification": bool(draft.get("sem_notificacao")),
        }
        result = await _telegram_upload_call(
            bot_token,
            method,
            payload,
            field_name=field_name,
            file_bytes=file_bytes,
            filename=str(draft.get("media_filename") or "arquivo"),
            mime=str(draft.get("media_mime") or "application/octet-stream"),
        )
    else:
        if not texto:
            raise RadioError("Rascunho sem texto.")
        result = await _telegram_json_call(
            bot_token,
            "sendMessage",
            {
                "chat_id": palco_id,
                "text": texto[:MAX_TEXT_LEN],
                "disable_web_page_preview": bool(draft.get("sem_preview")),
                "disable_notification": bool(draft.get("sem_notificacao")),
            },
        )
    if not isinstance(result, dict) or result.get("message_id") is None:
        raise MesaError("telegram_resposta_invalida")
    message_date = None
    try:
        message_date = int(result.get("date") or 0) or None
    except Exception:
        message_date = None
    resumo = str(draft.get("resumo_publico") or "Publicação Radio")
    msg_ref = register_mensagem_ref(
        chat_id=palco_id,
        message_id=int(result["message_id"]),
        resumo_publico=resumo,
        alias_secret=alias_secret,
        message_unix_time=message_date,
        db_engine=db_engine,
    )
    fixacao: dict[str, object] | None = None
    if bool(draft.get("fixar")):
        try:
            await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right="can_pin_messages")
            await _telegram_json_call(
                bot_token,
                "pinChatMessage",
                {"chat_id": palco_id, "message_id": int(result["message_id"]), "disable_notification": True},
            )
            fixacao = {"ok": True}
        except MesaError as exc:
            fixacao = {"ok": False, "motivo": _safe_text(exc, fallback="Não foi possível fixar.")}
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_radio_drafts
                SET status='published', msg_ref=:msg_ref, media_base64=NULL, updated_at=:updated_at
                WHERE palco_ref=:palco_ref AND draft_ref=:draft_ref
                """
            ),
            {"msg_ref": msg_ref, "updated_at": now, "palco_ref": palco_ref, "draft_ref": draft_ref},
        )
    history_ref = _history_ref(palco_ref=palco_ref, msg_ref=msg_ref, created_at=now, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO eq_radio_history (
                    event_ref, telegram_chat_id, palco_ref, ator_ref, draft_ref, msg_ref, tipo,
                    resumo_publico, media_kind, fixar, fixado, created_at
                ) VALUES (
                    :event_ref, :telegram_chat_id, :palco_ref, :ator_ref, :draft_ref, :msg_ref, :tipo,
                    :resumo_publico, :media_kind, :fixar, :fixado, :created_at
                )
                """
            ),
            {
                "event_ref": history_ref,
                "telegram_chat_id": palco_id,
                "palco_ref": palco_ref,
                "ator_ref": ator_ref,
                "draft_ref": draft_ref,
                "msg_ref": msg_ref,
                "tipo": str(draft.get("tipo") or "text"),
                "resumo_publico": resumo,
                "media_kind": media_kind or None,
                "fixar": 1 if bool(draft.get("fixar")) else 0,
                "fixado": 1 if isinstance(fixacao, dict) and bool(fixacao.get("ok")) else 0,
                "created_at": now,
            },
        )
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=palco_ref,
        alvo_ref=msg_ref,
        ajuste="radio.publicar",
        status="ok",
        resumo_publico=f"Radio publicado: {resumo}",
        payload_tecnico={"tipo": str(draft.get("tipo")), "media_kind": media_kind or None, "fixar": bool(draft.get("fixar")), "radio_history_ref": history_ref},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    row = _get_draft(palco_ref=palco_ref, draft_ref=draft_ref, db_engine=db_engine)
    return {"ok": True, "rascunho": public_radio_draft_row(row), "mensagem": {"msg_ref": msg_ref, "resumo": resumo}, "fixacao": fixacao, "historico": historico}


def cancelar_rascunho_radio(*, palco: dict[str, object], ator_ref: str, draft_ref: str, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    palco_ref = str(palco["ui_ref"])
    draft = _get_draft(palco_ref=palco_ref, draft_ref=draft_ref, db_engine=db_engine)
    if str(draft.get("status")) != "draft":
        raise RadioError("Apenas rascunhos abertos podem ser cancelados.")
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_radio_drafts
                SET status='cancelled', media_base64=NULL, updated_at=:updated_at
                WHERE palco_ref=:palco_ref AND draft_ref=:draft_ref
                """
            ),
            {"updated_at": now, "palco_ref": palco_ref, "draft_ref": draft_ref},
        )
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=palco_ref,
        alvo_ref=str(draft_ref),
        ajuste="radio.cancelar",
        status="ok",
        resumo_publico="Rascunho Radio cancelado.",
        payload_tecnico={},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    row = _get_draft(palco_ref=palco_ref, draft_ref=draft_ref, db_engine=db_engine)
    return {"ok": True, "rascunho": public_radio_draft_row(row), "historico": historico}



def _schedule_ref(*, palco_ref: str, ator_ref: str, scheduled_for: str, alias_secret: str) -> str:
    seed = f"radio_schedule:{palco_ref}:{ator_ref}:{scheduled_for}:{_now_iso()}"
    return "sch_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _broadcast_ref(*, ator_ref: str, created_at: str, alias_secret: str) -> str:
    seed = f"radio_broadcast:{ator_ref}:{created_at}"
    return "brd_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _parse_hhmm(value: object, *, fallback: str) -> str:
    text_value = str(value or "").strip() or fallback
    match = re.match(r"^(\d{1,2}):(\d{2})$", text_value)
    if not match:
        return fallback
    hour = int(match.group(1)); minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return f"{hour:02d}:{minute:02d}"


def _zoneinfo_or_default(name: object) -> ZoneInfo:
    tz_name = str(name or "America/Sao_Paulo").strip() or "America/Sao_Paulo"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_scheduled_for(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise RadioError("Informe data e hora do agendamento.")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RadioError("Data e hora do agendamento inválidas.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zoneinfo_or_default("America/Sao_Paulo"))
    utc_dt = dt.astimezone(timezone.utc)
    if utc_dt <= datetime.now(timezone.utc) + timedelta(seconds=20):
        raise RadioError("Agendamento precisa ficar alguns segundos no futuro.")
    return utc_dt.isoformat()


def _quiet_row_public(row: dict[str, Any] | None) -> dict[str, object]:
    if not row:
        return {"enabled": False, "start_hhmm": "22:00", "end_hhmm": "08:00", "timezone_name": "America/Sao_Paulo", "ativo_agora": False, "updated_at": ""}
    ativo = is_quiet_now_from_policy(row)
    return {
        "enabled": bool(row.get("enabled")),
        "start_hhmm": str(row.get("start_hhmm") or "22:00"),
        "end_hhmm": str(row.get("end_hhmm") or "08:00"),
        "timezone_name": str(row.get("timezone_name") or "America/Sao_Paulo"),
        "ativo_agora": bool(ativo),
        "updated_at": str(row.get("updated_at") or ""),
    }


def is_quiet_now_from_policy(row: dict[str, Any] | None, *, now_utc: datetime | None = None) -> bool:
    if not row or not bool(row.get("enabled")):
        return False
    tz = _zoneinfo_or_default(row.get("timezone_name"))
    now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    start = _parse_hhmm(row.get("start_hhmm"), fallback="22:00")
    end = _parse_hhmm(row.get("end_hhmm"), fallback="08:00")
    sh, sm = map(int, start.split(":")); eh, em = map(int, end.split(":"))
    start_minutes = sh * 60 + sm; end_minutes = eh * 60 + em; current = now.hour * 60 + now.minute
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= current < end_minutes
    return current >= start_minutes or current < end_minutes


def get_radio_quiet_policy_publico(*, palco_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM eq_radio_quiet_policies WHERE palco_ref=:palco_ref LIMIT 1"), {"palco_ref": str(palco_ref)}).mappings().first()
    return _quiet_row_public(dict(row) if row else None)


def salvar_radio_quiet_policy(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    palco_ref = str(palco["ui_ref"])
    now = _now_iso()
    start = _parse_hhmm(payload.get("start_hhmm"), fallback="22:00")
    end = _parse_hhmm(payload.get("end_hhmm"), fallback="08:00")
    tz_name = str(payload.get("timezone_name") or "America/Sao_Paulo").strip()[:64] or "America/Sao_Paulo"
    # Validate without failing the whole UI; unknown TZ is normalized to UTC for runtime but kept visible as UTC.
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = "UTC"
    enabled = 1 if bool(payload.get("enabled", False)) else 0
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_radio_quiet_policies (palco_ref, telegram_chat_id, enabled, start_hhmm, end_hhmm, timezone_name, updated_by_ref, updated_at)
                VALUES (:palco_ref, :telegram_chat_id, :enabled, :start_hhmm, :end_hhmm, :timezone_name, :updated_by_ref, :updated_at)
                ON CONFLICT(palco_ref) DO UPDATE SET
                    enabled=excluded.enabled,
                    start_hhmm=excluded.start_hhmm,
                    end_hhmm=excluded.end_hhmm,
                    timezone_name=excluded.timezone_name,
                    updated_by_ref=excluded.updated_by_ref,
                    updated_at=excluded.updated_at
                """
            ),
            {"palco_ref": palco_ref, "telegram_chat_id": int(palco["telegram_chat_id"]), "enabled": enabled, "start_hhmm": start, "end_hhmm": end, "timezone_name": tz_name, "updated_by_ref": ator_ref, "updated_at": now},
        )
    record_historico(
        ator_ref=ator_ref,
        palco_ref=palco_ref,
        alvo_ref=None,
        ajuste="radio.silencio.salvar",
        status="ok",
        resumo_publico=f"Janela de silêncio do Radio {'ativada' if enabled else 'desativada'}.",
        payload_tecnico={"start_hhmm": start, "end_hhmm": end, "timezone_name": tz_name},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {"ok": True, "quiet": get_radio_quiet_policy_publico(palco_ref=palco_ref, db_engine=db_engine)}


def _text_from_payload_or_template(*, palco_ref: str, payload: dict[str, Any], db_engine: Engine) -> tuple[str, str | None]:
    template_ref = str(payload.get("template_ref") or "").strip()
    if template_ref:
        template = _get_template(palco_ref=palco_ref, template_ref=template_ref, db_engine=db_engine)
        return str(template.get("texto") or "").strip(), template_ref
    texto = str(payload.get("texto") or "").strip()
    if not texto:
        raise RadioError("Informe texto ou escolha modelo do Radio.")
    if len(texto) > MAX_TEXT_LEN:
        raise RadioError("Texto acima do limite do Telegram.")
    return texto, None


def public_radio_schedule_row(row: dict[str, Any]) -> dict[str, object]:
    return {
        "schedule_ref": str(row.get("schedule_ref") or ""),
        "template_ref": str(row.get("template_ref") or ""),
        "resumo": _safe_text(row.get("texto"), fallback="Agendamento Radio")[:160],
        "sem_preview": bool(row.get("sem_preview")),
        "sem_notificacao": bool(row.get("sem_notificacao")),
        "fixar": bool(row.get("fixar")),
        "respeitar_silencio": bool(row.get("respeitar_silencio")),
        "status": str(row.get("status") or "scheduled"),
        "scheduled_for": str(row.get("scheduled_for") or ""),
        "last_error": _safe_text(row.get("last_error"), fallback=""),
        "msg_ref": str(row.get("msg_ref") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def list_radio_schedules_publicos(*, palco_ref: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_radio_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT schedule_ref, template_ref, texto, sem_preview, sem_notificacao, fixar, respeitar_silencio, status, scheduled_for, last_error, msg_ref, created_at, updated_at
                FROM eq_radio_schedules
                WHERE palco_ref=:palco_ref
                ORDER BY CASE status WHEN 'scheduled' THEN 0 WHEN 'deferred_quiet' THEN 1 WHEN 'published' THEN 2 ELSE 3 END, scheduled_for ASC, id DESC
                LIMIT 50
                """
            ),
            {"palco_ref": str(palco_ref)},
        ).mappings().all()
    return [public_radio_schedule_row(dict(row)) for row in rows]


def criar_radio_schedule(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    palco_ref = str(palco["ui_ref"])
    texto, template_ref = _text_from_payload_or_template(palco_ref=palco_ref, payload=payload, db_engine=db_engine)
    scheduled_for = _parse_scheduled_for(payload.get("scheduled_for"))
    created_at = _now_iso()
    schedule_ref = _schedule_ref(palco_ref=palco_ref, ator_ref=ator_ref, scheduled_for=scheduled_for, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_radio_schedules (
                    schedule_ref, telegram_chat_id, palco_ref, ator_ref, template_ref, texto,
                    sem_preview, sem_notificacao, fixar, respeitar_silencio, status, scheduled_for, created_at, updated_at
                ) VALUES (
                    :schedule_ref, :telegram_chat_id, :palco_ref, :ator_ref, :template_ref, :texto,
                    :sem_preview, :sem_notificacao, :fixar, :respeitar_silencio, 'scheduled', :scheduled_for, :created_at, :updated_at
                )
                """
            ),
            {
                "schedule_ref": schedule_ref,
                "telegram_chat_id": int(palco["telegram_chat_id"]),
                "palco_ref": palco_ref,
                "ator_ref": ator_ref,
                "template_ref": template_ref,
                "texto": texto,
                "sem_preview": 1 if bool(payload.get("sem_preview", True)) else 0,
                "sem_notificacao": 1 if bool(payload.get("sem_notificacao", False)) else 0,
                "fixar": 1 if bool(payload.get("fixar", False)) else 0,
                "respeitar_silencio": 1 if bool(payload.get("respeitar_silencio", True)) else 0,
                "scheduled_for": scheduled_for,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
    return public_radio_schedule_row({"schedule_ref": schedule_ref, "template_ref": template_ref, "texto": texto, "sem_preview": bool(payload.get("sem_preview", True)), "sem_notificacao": bool(payload.get("sem_notificacao", False)), "fixar": bool(payload.get("fixar", False)), "respeitar_silencio": bool(payload.get("respeitar_silencio", True)), "status": "scheduled", "scheduled_for": scheduled_for, "created_at": created_at, "updated_at": created_at})


def cancelar_radio_schedule(
    *,
    palco: dict[str, object],
    ator_ref: str,
    schedule_ref: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    palco_ref = str(palco["ui_ref"])
    now = _now_iso()
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM eq_radio_schedules WHERE palco_ref=:palco_ref AND schedule_ref=:schedule_ref LIMIT 1"), {"palco_ref": palco_ref, "schedule_ref": str(schedule_ref)}).mappings().first()
        if not row:
            raise RadioNotFoundError("agendamento_indisponivel")
        if str(row.get("status")) not in {"scheduled", "deferred_quiet"}:
            raise RadioError("Agendamento já encerrado.")
        conn.execute(text("UPDATE eq_radio_schedules SET status='cancelled', updated_at=:updated_at WHERE palco_ref=:palco_ref AND schedule_ref=:schedule_ref"), {"updated_at": now, "palco_ref": palco_ref, "schedule_ref": str(schedule_ref)})
    record_historico(ator_ref=ator_ref, palco_ref=palco_ref, alvo_ref=str(schedule_ref), ajuste="radio.agendamento.cancelar", status="ok", resumo_publico="Agendamento Radio cancelado.", payload_tecnico={}, alias_secret=alias_secret, db_engine=db_engine)
    row = dict(row); row["status"] = "cancelled"; row["updated_at"] = now
    return {"ok": True, "agendamento": public_radio_schedule_row(row)}


async def _send_radio_text_publication(
    *,
    palco_id: int,
    palco_ref: str,
    ator_ref: str,
    texto: str,
    sem_preview: bool,
    sem_notificacao: bool,
    fixar: bool,
    bot_token: str,
    alias_secret: str,
    db_engine: Engine,
    history_draft_ref: str | None = None,
) -> dict[str, object]:
    await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right=None)
    result = await _telegram_json_call(
        bot_token,
        "sendMessage",
        {"chat_id": palco_id, "text": texto[:MAX_TEXT_LEN], "disable_web_page_preview": sem_preview, "disable_notification": sem_notificacao},
    )
    if not isinstance(result, dict) or result.get("message_id") is None:
        raise MesaError("telegram_resposta_invalida")
    msg_ref = register_mensagem_ref(
        chat_id=palco_id,
        message_id=int(result["message_id"]),
        resumo_publico=_safe_text(texto.replace("\n", " "), fallback="Publicação Radio")[:120],
        alias_secret=alias_secret,
        message_unix_time=int(result.get("date") or 0) or None,
        db_engine=db_engine,
    )
    fixado = False
    if fixar:
        await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right="can_pin_messages")
        await _telegram_json_call(bot_token, "pinChatMessage", {"chat_id": palco_id, "message_id": int(result["message_id"]), "disable_notification": True})
        fixado = True
    now = _now_iso()
    event_ref = _history_ref(palco_ref=palco_ref, msg_ref=msg_ref, created_at=now, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO eq_radio_history (
                    event_ref, telegram_chat_id, palco_ref, ator_ref, draft_ref, msg_ref, tipo,
                    resumo_publico, media_kind, fixar, fixado, created_at
                ) VALUES (
                    :event_ref, :telegram_chat_id, :palco_ref, :ator_ref, :draft_ref, :msg_ref, 'text',
                    :resumo_publico, NULL, :fixar, :fixado, :created_at
                )
                """
            ),
            {"event_ref": event_ref, "telegram_chat_id": palco_id, "palco_ref": palco_ref, "ator_ref": ator_ref, "draft_ref": history_draft_ref, "msg_ref": msg_ref, "resumo_publico": _safe_text(texto.replace("\n", " "), fallback="Publicação Radio")[:180], "fixar": 1 if fixar else 0, "fixado": 1 if fixado else 0, "created_at": now},
        )
    return {"ok": True, "msg_ref": msg_ref, "fixado": fixado, "event_ref": event_ref}


async def run_due_radio_schedules(
    *,
    bot_token: str,
    alias_secret: str,
    limit: int = 10,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    now = _now_iso()
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM eq_radio_schedules
                WHERE status IN ('scheduled','deferred_quiet') AND scheduled_for <= :now
                ORDER BY scheduled_for ASC, id ASC
                LIMIT :limit
                """
            ),
            {"now": now, "limit": max(1, min(int(limit or 10), 25))},
        ).mappings().all()
    enviados = 0; adiados = 0; falhas = 0
    detalhes: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        palco_ref = str(item["palco_ref"])
        quiet = None
        if bool(item.get("respeitar_silencio")):
            with db_engine.begin() as conn:
                q = conn.execute(text("SELECT * FROM eq_radio_quiet_policies WHERE palco_ref=:palco_ref LIMIT 1"), {"palco_ref": palco_ref}).mappings().first()
            quiet = dict(q) if q else None
        if is_quiet_now_from_policy(quiet):
            next_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            with db_engine.begin() as conn:
                conn.execute(text("UPDATE eq_radio_schedules SET status='deferred_quiet', scheduled_for=:next_time, updated_at=:updated_at WHERE schedule_ref=:schedule_ref"), {"next_time": next_time, "updated_at": _now_iso(), "schedule_ref": item["schedule_ref"]})
            adiados += 1
            detalhes.append({"schedule_ref": item["schedule_ref"], "status": "adiado_silencio"})
            continue
        try:
            result = await _send_radio_text_publication(palco_id=int(item["telegram_chat_id"]), palco_ref=palco_ref, ator_ref=str(item["ator_ref"]), texto=str(item["texto"]), sem_preview=bool(item.get("sem_preview")), sem_notificacao=bool(item.get("sem_notificacao")), fixar=bool(item.get("fixar")), bot_token=bot_token, alias_secret=alias_secret, db_engine=db_engine, history_draft_ref=str(item["schedule_ref"]))
            with db_engine.begin() as conn:
                conn.execute(text("UPDATE eq_radio_schedules SET status='published', msg_ref=:msg_ref, last_error=NULL, updated_at=:updated_at WHERE schedule_ref=:schedule_ref"), {"msg_ref": result.get("msg_ref"), "updated_at": _now_iso(), "schedule_ref": item["schedule_ref"]})
            enviados += 1
            detalhes.append({"schedule_ref": item["schedule_ref"], "status": "publicado", "msg_ref": result.get("msg_ref")})
        except Exception as exc:
            falhas += 1
            public_error = radio_error_public_detail(exc)
            with db_engine.begin() as conn:
                conn.execute(text("UPDATE eq_radio_schedules SET status='failed', last_error=:last_error, updated_at=:updated_at WHERE schedule_ref=:schedule_ref"), {"last_error": public_error, "updated_at": _now_iso(), "schedule_ref": item["schedule_ref"]})
            detalhes.append({"schedule_ref": item["schedule_ref"], "status": "falhou", "motivo": public_error})
    return {"ok": True, "processados": len(rows), "enviados": enviados, "adiados": adiados, "falhas": falhas, "detalhes": detalhes}


async def executar_radio_broadcast(
    *,
    palcos: list[dict[str, object]],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_radio_tables(db_engine)
    if not palcos:
        raise RadioError("Nenhum grupo disponível para broadcast.")
    # Use the first palco only to resolve a template when provided; templates are scoped by group.
    texto, template_ref = _text_from_payload_or_template(palco_ref=str(palcos[0]["ui_ref"]), payload=payload, db_engine=db_engine)
    respeitar_silencio = bool(payload.get("respeitar_silencio", True))
    sem_preview = bool(payload.get("sem_preview", True)); sem_notificacao = bool(payload.get("sem_notificacao", False)); fixar = bool(payload.get("fixar", False))
    created_at = _now_iso()
    broadcast_ref = _broadcast_ref(ator_ref=ator_ref, created_at=created_at, alias_secret=alias_secret)
    enviados = 0; pulados = 0; falhas = 0; resultados: list[dict[str, object]] = []
    for palco in palcos[:25]:
        palco_ref = str(palco["ui_ref"]); palco_id = int(palco["telegram_chat_id"])
        if respeitar_silencio:
            quiet = get_radio_quiet_policy_publico(palco_ref=palco_ref, db_engine=db_engine)
            if quiet.get("ativo_agora"):
                pulados += 1
                resultados.append({"palco_ref": palco_ref, "status": "pulado_silencio"})
                continue
        try:
            result = await _send_radio_text_publication(palco_id=palco_id, palco_ref=palco_ref, ator_ref=ator_ref, texto=texto, sem_preview=sem_preview, sem_notificacao=sem_notificacao, fixar=fixar, bot_token=bot_token, alias_secret=alias_secret, db_engine=db_engine, history_draft_ref=broadcast_ref)
            enviados += 1
            resultados.append({"palco_ref": palco_ref, "status": "enviado", "msg_ref": result.get("msg_ref")})
        except Exception as exc:
            falhas += 1
            resultados.append({"palco_ref": palco_ref, "status": "falhou", "motivo": radio_error_public_detail(exc)})
    resumo = f"Broadcast Radio: {enviados} enviado(s), {pulados} pulado(s), {falhas} falha(s)."
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_radio_broadcasts (broadcast_ref, ator_ref, texto, total_alvos, enviados, pulados, falhas, resumo_publico, created_at)
                VALUES (:broadcast_ref, :ator_ref, :texto, :total_alvos, :enviados, :pulados, :falhas, :resumo_publico, :created_at)
                """
            ),
            {"broadcast_ref": broadcast_ref, "ator_ref": ator_ref, "texto": texto[:MAX_TEXT_LEN], "total_alvos": len(palcos[:25]), "enviados": enviados, "pulados": pulados, "falhas": falhas, "resumo_publico": resumo, "created_at": created_at},
        )
    return {"ok": True, "broadcast_ref": broadcast_ref, "template_ref": template_ref or "", "resumo": resumo, "enviados": enviados, "pulados": pulados, "falhas": falhas, "resultados": resultados}
