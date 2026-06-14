from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import MesaError, ensure_bot_right, record_historico, register_mensagem_ref, telegram_api_call, _safe_text


class MultimediaError(RuntimeError):
    """Raised when a native Telegram multimedia flow cannot continue."""


ALLOWED_KINDS = {"text", "photo", "video", "document", "audio", "voice", "animation", "album"}
MULTIMEDIA_KIND_LABELS = {
    "text": "texto",
    "photo": "foto",
    "video": "vídeo",
    "document": "documento",
    "audio": "áudio",
    "voice": "voz",
    "animation": "animação",
    "album": "álbum",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_column_exists(conn: Any, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    return any(str(row.get("name")) == column for row in rows)


def ensure_multimedia_tables(db_engine: Engine = default_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_multimedia_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    ator_ref TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'awaiting',
                    texto TEXT,
                    media_kind TEXT,
                    file_id TEXT,
                    file_unique_id TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    msg_ref TEXT,
                    error_public TEXT,
                    source_chat_id INTEGER,
                    source_message_id INTEGER,
                    source_message_ids TEXT,
                    source_media_group_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        for column, ddl in (
            ("texto", "ALTER TABLE eq_multimedia_sessions ADD COLUMN texto TEXT"),
            ("media_kind", "ALTER TABLE eq_multimedia_sessions ADD COLUMN media_kind TEXT"),
            ("file_id", "ALTER TABLE eq_multimedia_sessions ADD COLUMN file_id TEXT"),
            ("file_unique_id", "ALTER TABLE eq_multimedia_sessions ADD COLUMN file_unique_id TEXT"),
            ("file_name", "ALTER TABLE eq_multimedia_sessions ADD COLUMN file_name TEXT"),
            ("mime_type", "ALTER TABLE eq_multimedia_sessions ADD COLUMN mime_type TEXT"),
            ("msg_ref", "ALTER TABLE eq_multimedia_sessions ADD COLUMN msg_ref TEXT"),
            ("error_public", "ALTER TABLE eq_multimedia_sessions ADD COLUMN error_public TEXT"),
            ("source_chat_id", "ALTER TABLE eq_multimedia_sessions ADD COLUMN source_chat_id INTEGER"),
            ("source_message_id", "ALTER TABLE eq_multimedia_sessions ADD COLUMN source_message_id INTEGER"),
            ("source_message_ids", "ALTER TABLE eq_multimedia_sessions ADD COLUMN source_message_ids TEXT"),
            ("source_media_group_id", "ALTER TABLE eq_multimedia_sessions ADD COLUMN source_media_group_id TEXT"),
        ):
            if not _sqlite_column_exists(conn, "eq_multimedia_sessions", column):
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_owner ON eq_multimedia_sessions(telegram_user_id, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_palco ON eq_multimedia_sessions(palco_ref, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_ref ON eq_multimedia_sessions(session_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_album ON eq_multimedia_sessions(telegram_user_id, source_media_group_id, updated_at)"))


def _session_ref(*, palco_ref: str, ator_ref: str, user_id: int, alias_secret: str) -> str:
    seed = f"multimidia:{palco_ref}:{ator_ref}:{user_id}:{_now_iso()}"
    return "mm_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _status_public_label(status: str) -> str:
    return {
        "awaiting": "Aguardando conteúdo",
        "ready": "Pronto para publicar",
        "publishing": "Publicando",
        "published": "Publicado",
        "failed": "Falhou",
        "conflict": "Conflito",
        "cancelled": "Cancelado",
    }.get(str(status or ""), str(status or "sessão"))


def _tipo_public_label(kind: str) -> str:
    return MULTIMEDIA_KIND_LABELS.get(str(kind or ""), str(kind or "conteúdo"))



def _json_message_ids(value: object) -> list[int]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value or "[]"))
        except Exception:
            raw = []
    ids: list[int] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(dict.fromkeys(ids))


def _append_message_id(existing: object, message_id: object) -> str:
    ids = _json_message_ids(existing)
    try:
        ids.append(int(message_id))
    except (TypeError, ValueError):
        pass
    return json.dumps(sorted(dict.fromkeys(ids)))


def _copy_result_ids(result: object) -> list[int]:
    if isinstance(result, dict):
        result = [result]
    ids: list[int] = []
    if isinstance(result, list):
        for item in result:
            value = getattr(item, "message_id", None)
            if value is None and isinstance(item, dict):
                value = item.get("message_id")
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    return ids


def _source_ids_from_session(session: dict[str, Any]) -> list[int]:
    ids = _json_message_ids(session.get("source_message_ids"))
    if not ids and session.get("source_message_id") is not None:
        try:
            ids.append(int(session["source_message_id"]))
        except (TypeError, ValueError):
            pass
    return sorted(dict.fromkeys(ids))


def _album_session_for_user(*, telegram_user_id: int, source_media_group_id: str, db_engine: Engine = default_engine) -> dict[str, Any] | None:
    if not source_media_group_id:
        return None
    ensure_multimedia_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM eq_multimedia_sessions
                WHERE telegram_user_id=:user_id AND source_media_group_id=:media_group_id
                  AND status IN ('awaiting','ready')
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"user_id": int(telegram_user_id), "media_group_id": str(source_media_group_id)},
        ).mappings().first()
    return dict(row) if row else None

def _session_next_step(status: str, kind: str, row: dict[str, Any]) -> tuple[str, bool, str]:
    status = str(status or "awaiting")
    kind = str(kind or "")
    if status == "awaiting":
        return "Envie texto ou mídia no privado do bot.", False, "aguardando_conteudo"
    if status == "ready":
        return "Confirme a publicação no Web App.", True, "pronto"
    if status == "publishing":
        return "Publicação em andamento. Atualize a lista em alguns segundos.", False, "publicando"
    if status == "published":
        return "Sessão já publicada.", False, "publicado"
    if status == "failed":
        return _safe_text(row.get("error_public"), fallback="Falha registrada. Crie nova sessão se necessário."), False, "falhou"
    if status == "cancelled":
        return "Sessão cancelada.", False, "cancelado"
    return "Atualize a lista para conferir o estado real.", False, "estado_desconhecido"


def public_multimedia_session(row: dict[str, Any]) -> dict[str, object]:
    status = str(row.get("status") or "awaiting")
    kind = str(row.get("media_kind") or ("text" if row.get("texto") else ""))
    next_step, pode_publicar, codigo_estado = _session_next_step(status, kind, row)
    tem_conteudo = bool(row.get("texto") or row.get("file_id"))
    source_ids = _source_ids_from_session(row)
    return {
        "session_ref": str(row.get("session_ref") or ""),
        "status": status,
        "estado": _status_public_label(status),
        "tipo": kind,
        "tipo_label": _tipo_public_label(kind),
        "tem_conteudo": tem_conteudo or bool(source_ids),
        "modo": "copia_nativa" if source_ids else "envio_legado",
        "album_itens": len(source_ids) if str(row.get("source_media_group_id") or "") else 0,
        "pode_publicar": pode_publicar,
        "codigo_estado": codigo_estado,
        "proximo_passo": next_step,
        "resumo": _safe_text(row.get("texto"), fallback=_safe_text(row.get("file_name"), fallback=(f"Álbum com {len(source_ids)} item(ns)" if str(row.get("source_media_group_id") or "") else "Aguardando conteúdo")))[:160],
        "arquivo": _safe_text(row.get("file_name"), fallback=""),
        "mime": _safe_text(row.get("mime_type"), fallback=""),
        "msg_ref": str(row.get("msg_ref") or ""),
        "erro": _safe_text(row.get("error_public"), fallback=""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def create_multimedia_session(*, palco: dict[str, object], ator_ref: str, telegram_user_id: int, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_multimedia_tables(db_engine)
    now = _now_iso()
    ref = _session_ref(palco_ref=str(palco["ui_ref"]), ator_ref=ator_ref, user_id=int(telegram_user_id), alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_multimedia_sessions (
                    session_ref, telegram_chat_id, palco_ref, ator_ref, telegram_user_id, status, created_at, updated_at
                ) VALUES (
                    :session_ref, :telegram_chat_id, :palco_ref, :ator_ref, :telegram_user_id, 'awaiting', :created_at, :updated_at
                )
                """
            ),
            {
                "session_ref": ref,
                "telegram_chat_id": int(palco["telegram_chat_id"]),
                "palco_ref": str(palco["ui_ref"]),
                "ator_ref": ator_ref,
                "telegram_user_id": int(telegram_user_id),
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_multimedia_session(session_ref=ref, db_engine=db_engine)


def get_multimedia_session(*, session_ref: str, db_engine: Engine = default_engine) -> dict[str, Any]:
    ensure_multimedia_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM eq_multimedia_sessions WHERE session_ref=:ref LIMIT 1"), {"ref": str(session_ref)}).mappings().first()
    if not row:
        raise MultimediaError("Sessão multimídia indisponível.")
    return dict(row)


def list_multimedia_sessions(*, palco_ref: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_multimedia_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM eq_multimedia_sessions
                WHERE palco_ref=:palco_ref
                ORDER BY updated_at DESC, id DESC
                LIMIT 30
                """
            ),
            {"palco_ref": str(palco_ref)},
        ).mappings().all()
    return [public_multimedia_session(dict(row)) for row in rows]


def active_session_for_user(*, telegram_user_id: int, db_engine: Engine = default_engine) -> dict[str, Any] | None:
    ensure_multimedia_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM eq_multimedia_sessions
                WHERE telegram_user_id=:user_id AND status='awaiting'
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"user_id": int(telegram_user_id)},
        ).mappings().first()
    return dict(row) if row else None



def extract_multimedia_session_ref(text_value: str) -> str:
    match = re.search(r"\bmm_[A-Za-z0-9]{6,32}\b", str(text_value or ""))
    return match.group(0) if match else ""


def session_for_incoming_message(*, telegram_user_id: int, session_ref_hint: str = "", db_engine: Engine = default_engine) -> dict[str, Any] | None:
    ensure_multimedia_tables(db_engine)
    hint = str(session_ref_hint or "").strip()
    if hint:
        with db_engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT * FROM eq_multimedia_sessions
                    WHERE session_ref=:session_ref AND telegram_user_id=:user_id
                      AND status IN ('awaiting','ready')
                    LIMIT 1
                    """
                ),
                {"session_ref": hint, "user_id": int(telegram_user_id)},
            ).mappings().first()
        if row:
            return dict(row)
    return active_session_for_user(telegram_user_id=int(telegram_user_id), db_engine=db_engine)


def mark_session_waiting(*, session_ref: str, telegram_user_id: int, db_engine: Engine = default_engine) -> dict[str, object]:
    session = get_multimedia_session(session_ref=session_ref, db_engine=db_engine)
    if int(session.get("telegram_user_id") or 0) != int(telegram_user_id):
        raise MultimediaError("Sessão pertence a outro usuário.")
    current_status = str(session.get("status") or "awaiting")
    if current_status in {"published", "cancelled"}:
        raise MultimediaError("Sessão já encerrada.")
    # Reabrir o deep link não pode apagar uma mídia já recebida. Antes disso, a sessão
    # voltava para awaiting e gerava 409 mesmo depois de o bot receber o conteúdo.
    if current_status == "ready":
        return public_multimedia_session(session)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_multimedia_sessions SET status='awaiting', updated_at=:updated_at WHERE session_ref=:ref"),
            {"updated_at": _now_iso(), "ref": str(session_ref)},
        )
    return public_multimedia_session(get_multimedia_session(session_ref=session_ref, db_engine=db_engine))


def attach_telegram_message_to_session(*, telegram_user_id: int, message_data: dict[str, Any], session_ref_hint: str = "", db_engine: Engine = default_engine) -> dict[str, object] | None:
    source_media_group_id = _safe_text(message_data.get("source_media_group_id"), fallback="")[:120]
    session = session_for_incoming_message(telegram_user_id=int(telegram_user_id), session_ref_hint=session_ref_hint, db_engine=db_engine)
    if not session and source_media_group_id:
        session = _album_session_for_user(telegram_user_id=int(telegram_user_id), source_media_group_id=source_media_group_id, db_engine=db_engine)
    if not session:
        return None
    kind = str(message_data.get("media_kind") or "text")
    if source_media_group_id:
        kind = "album"
    if kind not in ALLOWED_KINDS:
        raise MultimediaError("Tipo de mídia indisponível.")
    texto = _safe_text(message_data.get("texto"), fallback="")[:1024 if kind not in {"text", "album"} else 4096]
    file_id = _safe_text(message_data.get("file_id"), fallback="")[:260]
    source_chat_id = message_data.get("source_chat_id")
    source_message_id = message_data.get("source_message_id")
    try:
        source_chat_id_int = int(source_chat_id) if source_chat_id is not None else None
        source_message_id_int = int(source_message_id) if source_message_id is not None else None
    except (TypeError, ValueError) as exc:
        raise MultimediaError("Origem da mensagem indisponível.") from exc
    if kind != "text" and not file_id and not source_message_id_int:
        raise MultimediaError("Arquivo não recebido pelo bot.")
    existing_ids = session.get("source_message_ids")
    source_message_ids = _append_message_id(existing_ids, source_message_id_int) if source_message_id_int else str(existing_ids or "[]")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_multimedia_sessions
                SET status='ready', texto=:texto, media_kind=:media_kind, file_id=:file_id,
                    file_unique_id=:file_unique_id, file_name=:file_name, mime_type=:mime_type,
                    source_chat_id=:source_chat_id, source_message_id=COALESCE(source_message_id, :source_message_id),
                    source_message_ids=:source_message_ids, source_media_group_id=COALESCE(source_media_group_id, :source_media_group_id),
                    error_public=NULL, updated_at=:updated_at
                WHERE session_ref=:session_ref
                """
            ),
            {
                "texto": texto or _safe_text(session.get("texto"), fallback=""),
                "media_kind": kind,
                "file_id": file_id or session.get("file_id"),
                "file_unique_id": _safe_text(message_data.get("file_unique_id"), fallback="")[:260] or session.get("file_unique_id"),
                "file_name": _safe_text(message_data.get("file_name"), fallback="")[:180] or session.get("file_name"),
                "mime_type": _safe_text(message_data.get("mime_type"), fallback="")[:120] or session.get("mime_type"),
                "source_chat_id": source_chat_id_int,
                "source_message_id": source_message_id_int,
                "source_message_ids": source_message_ids,
                "source_media_group_id": source_media_group_id or None,
                "updated_at": _now_iso(),
                "session_ref": str(session["session_ref"]),
            },
        )
    return public_multimedia_session(get_multimedia_session(session_ref=str(session["session_ref"]), db_engine=db_engine))



def multimedia_center_public(*, palco_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    """Resumo operacional do centro multimídia.

    Não expõe file_id nem identificadores internos de Telegram. Serve para a UI
    decidir se há sessão pronta, aguardando conteúdo, publicada ou falha.
    """
    sessoes = list_multimedia_sessions(palco_ref=palco_ref, db_engine=db_engine)
    resumo = {
        "total": len(sessoes),
        "aguardando": 0,
        "prontas": 0,
        "publicando": 0,
        "publicadas": 0,
        "falhas": 0,
    }
    for sessao in sessoes:
        status = str(sessao.get("status") or "")
        if status == "awaiting":
            resumo["aguardando"] += 1
        elif status == "ready":
            resumo["prontas"] += 1
        elif status == "publishing":
            resumo["publicando"] += 1
        elif status == "published":
            resumo["publicadas"] += 1
        elif status == "failed":
            resumo["falhas"] += 1
    return {
        "resumo": resumo,
        "sessoes": sessoes,
        "tipos_suportados": [
            {"tipo": key, "label": MULTIMEDIA_KIND_LABELS[key]}
            for key in ("text", "photo", "video", "document", "audio", "voice", "animation", "album")
        ],
        "instrucoes": [
            "Crie a sessão no Web App.",
            "Envie o conteúdo no privado do bot pelo Telegram.",
            "Volte ao Web App e confirme a publicação no grupo.",
        ],
    }


def multimedia_session_diagnostic(*, session_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    try:
        session = get_multimedia_session(session_ref=session_ref, db_engine=db_engine)
    except MultimediaError:
        return {"ok": False, "codigo": "sessao_indisponivel", "mensagem": "Sessão multimídia indisponível."}
    public = public_multimedia_session(session)
    missing = []
    if not public.get("tem_conteudo"):
        missing.append("conteúdo no privado do bot")
    if public.get("status") != "ready":
        missing.append("estado pronto")
    return {
        "ok": True,
        "sessao": public,
        "faltando": missing,
        "pode_publicar": bool(public.get("pode_publicar")),
        "mensagem": "Sessão pronta para publicar." if public.get("pode_publicar") else "Sessão ainda não está pronta.",
    }


def _method_for_kind(kind: str) -> tuple[str, str, str | None]:
    if kind == "photo":
        return "sendPhoto", "photo", "can_send_photos"
    if kind == "video":
        return "sendVideo", "video", "can_send_videos"
    if kind == "audio":
        return "sendAudio", "audio", None
    if kind == "voice":
        return "sendVoice", "voice", None
    if kind == "document":
        return "sendDocument", "document", "can_send_documents"
    if kind == "animation":
        return "sendAnimation", "animation", "can_send_documents"
    return "sendMessage", "text", None


async def publish_multimedia_session(*, palco: dict[str, object], ator_ref: str, session_ref: str, bot_token: str, alias_secret: str, fixar_silencio: bool = False, db_engine: Engine = default_engine) -> dict[str, object]:
    session = get_multimedia_session(session_ref=session_ref, db_engine=db_engine)
    if str(session.get("palco_ref")) != str(palco["ui_ref"]):
        raise MultimediaError("Sessão fora do grupo selecionado.")
    status = str(session.get("status") or "awaiting")
    if status == "published":
        raise MultimediaError("Sessão já publicada. Atualize a lista antes de tentar novamente.")
    if status == "publishing":
        raise MultimediaError("Sessão já está publicando. Aguarde a conclusão.")
    if status == "failed":
        raise MultimediaError(_safe_text(session.get("error_public"), fallback="Sessão falhou. Crie uma nova sessão."))
    if status != "ready":
        raise MultimediaError("Sessão ainda aguardando conteúdo. Envie texto ou mídia no privado do bot antes de publicar.")
    now = _now_iso()
    with db_engine.begin() as conn:
        result_update = conn.execute(
            text("""
                UPDATE eq_multimedia_sessions
                SET status='publishing', error_public=NULL, updated_at=:updated_at
                WHERE session_ref=:ref AND status='ready'
            """),
            {"updated_at": now, "ref": str(session_ref)},
        )
        if getattr(result_update, "rowcount", 0) != 1:
            raise MultimediaError("Sessão mudou de estado. Atualize a lista antes de publicar.")
    kind = str(session.get("media_kind") or "text")
    method, field_name, required_right = _method_for_kind(kind)
    chat_id = int(palco["telegram_chat_id"])
    published_ids: list[int] = []
    source_ids = _source_ids_from_session(session)
    try:
        await ensure_bot_right(bot_token=bot_token, chat_id=chat_id, required_right=required_right)
        if fixar_silencio:
            await ensure_bot_right(bot_token=bot_token, chat_id=chat_id, required_right="can_pin_messages")
        texto = str(session.get("texto") or "")
        source_chat_id = session.get("source_chat_id")
        if source_chat_id and source_ids:
            if len(source_ids) > 1:
                method = "copyMessages"
                result = await telegram_api_call(
                    bot_token,
                    method,
                    {"chat_id": chat_id, "from_chat_id": int(source_chat_id), "message_ids": source_ids, "disable_notification": True},
                )
                published_ids = _copy_result_ids(result)
            else:
                method = "copyMessage"
                result = await telegram_api_call(
                    bot_token,
                    method,
                    {"chat_id": chat_id, "from_chat_id": int(source_chat_id), "message_id": int(source_ids[0]), "disable_notification": True},
                )
                published_ids = _copy_result_ids(result)
        elif kind == "text":
            if not texto.strip():
                raise MultimediaError("Mensagem vazia.")
            payload: dict[str, Any] = {"chat_id": chat_id, "text": texto[:4096], "link_preview_options": {"is_disabled": True}}
            result = await telegram_api_call(bot_token, method, payload)
            published_ids = _copy_result_ids(result)
        else:
            file_id = str(session.get("file_id") or "")
            if not file_id:
                raise MultimediaError("Arquivo da sessão indisponível.")
            payload = {"chat_id": chat_id, field_name: file_id, "caption": texto[:1024] if texto else None}
            result = await telegram_api_call(bot_token, method, payload)
            published_ids = _copy_result_ids(result)
        if not published_ids:
            raise MultimediaError("Telegram não retornou a mensagem publicada.")
    except (MesaError, MultimediaError) as exc:
        public_error = _safe_text(exc, fallback="Publicação multimídia não concluída.")[:180]
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE eq_multimedia_sessions SET status='failed', error_public=:error, updated_at=:updated_at WHERE session_ref=:ref"),
                {"error": public_error, "updated_at": _now_iso(), "ref": str(session_ref)},
            )
        raise
    pin_status = "nao_solicitado"
    pin_error = ""
    if fixar_silencio:
        try:
            await telegram_api_call(
                bot_token,
                "pinChatMessage",
                {"chat_id": chat_id, "message_id": int(published_ids[0]), "disable_notification": True},
            )
            pin_status = "ok"
        except Exception as exc:  # publicação já aconteceu; não marca a sessão como falha para evitar duplicidade em retry.
            pin_status = "falhou"
            pin_error = _safe_text(exc, fallback="Falha ao fixar silenciosamente.")[:180]
    msg_refs: list[str] = []
    for idx, published_id in enumerate(published_ids, start=1):
        msg_refs.append(register_mensagem_ref(
            chat_id=chat_id,
            message_id=int(published_id),
            resumo_publico=_safe_text(str(session.get("texto") or ""), fallback="Publicação multimídia")[:140] + (f" ({idx}/{len(published_ids)})" if len(published_ids) > 1 else ""),
            alias_secret=alias_secret,
            message_unix_time=None,
            db_engine=db_engine,
        ))
    msg_ref = msg_refs[0]
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_multimedia_sessions SET status='published', msg_ref=:msg_ref, error_public=NULL, updated_at=:updated_at WHERE session_ref=:ref"),
            {"msg_ref": msg_ref, "updated_at": now, "ref": str(session_ref)},
        )
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=str(palco["ui_ref"]),
        alvo_ref=msg_ref,
        ajuste="multimidia.publicar",
        status="ok" if pin_status != "falhou" else "parcial",
        resumo_publico="Publicação multimídia enviada pelo bot." if pin_status != "ok" else "Publicação multimídia enviada e fixada silenciosamente.",
        payload_tecnico={
            "tipo": kind,
            "method": method,
            "source_message_ids": source_ids,
            "published_message_ids": published_ids,
            "msg_refs": msg_refs,
            "fixar_silencio": bool(fixar_silencio),
            "pin_status": pin_status,
            "pin_error": pin_error,
        },
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {
        "ok": True,
        "sessao": public_multimedia_session(get_multimedia_session(session_ref=session_ref, db_engine=db_engine)),
        "mensagem": {"msg_ref": msg_ref, "msg_refs": msg_refs},
        "fixacao": {"solicitada": bool(fixar_silencio), "status": pin_status, "erro": pin_error},
        "historico": historico,
    }
