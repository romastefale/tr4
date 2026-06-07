from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import MesaError, ensure_bot_right, record_historico, register_mensagem_ref, telegram_api_call, _safe_text


class MultimediaError(RuntimeError):
    """Raised when a native Telegram multimedia flow cannot continue."""


ALLOWED_KINDS = {"text", "photo", "video", "document", "audio", "voice"}


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
        ):
            if not _sqlite_column_exists(conn, "eq_multimedia_sessions", column):
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_owner ON eq_multimedia_sessions(telegram_user_id, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_palco ON eq_multimedia_sessions(palco_ref, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_multimedia_ref ON eq_multimedia_sessions(session_ref)"))


def _session_ref(*, palco_ref: str, ator_ref: str, user_id: int, alias_secret: str) -> str:
    seed = f"multimidia:{palco_ref}:{ator_ref}:{user_id}:{_now_iso()}"
    return "mm_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def public_multimedia_session(row: dict[str, Any]) -> dict[str, object]:
    return {
        "session_ref": str(row.get("session_ref") or ""),
        "status": str(row.get("status") or "awaiting"),
        "tipo": str(row.get("media_kind") or ("text" if row.get("texto") else "")),
        "resumo": _safe_text(row.get("texto"), fallback=_safe_text(row.get("file_name"), fallback="Aguardando conteúdo"))[:160],
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


def mark_session_waiting(*, session_ref: str, telegram_user_id: int, db_engine: Engine = default_engine) -> dict[str, object]:
    session = get_multimedia_session(session_ref=session_ref, db_engine=db_engine)
    if int(session.get("telegram_user_id") or 0) != int(telegram_user_id):
        raise MultimediaError("Sessão pertence a outro usuário.")
    if str(session.get("status")) in {"published", "cancelled"}:
        raise MultimediaError("Sessão já encerrada.")
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_multimedia_sessions SET status='awaiting', updated_at=:updated_at WHERE session_ref=:ref"),
            {"updated_at": _now_iso(), "ref": str(session_ref)},
        )
    return public_multimedia_session(get_multimedia_session(session_ref=session_ref, db_engine=db_engine))


def attach_telegram_message_to_session(*, telegram_user_id: int, message_data: dict[str, Any], db_engine: Engine = default_engine) -> dict[str, object] | None:
    session = active_session_for_user(telegram_user_id=int(telegram_user_id), db_engine=db_engine)
    if not session:
        return None
    kind = str(message_data.get("media_kind") or "text")
    if kind not in ALLOWED_KINDS:
        raise MultimediaError("Tipo de mídia indisponível.")
    texto = _safe_text(message_data.get("texto"), fallback="")[:1024 if kind != "text" else 4096]
    file_id = _safe_text(message_data.get("file_id"), fallback="")[:260]
    if kind != "text" and not file_id:
        raise MultimediaError("Arquivo não recebido pelo bot.")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_multimedia_sessions
                SET status='ready', texto=:texto, media_kind=:media_kind, file_id=:file_id,
                    file_unique_id=:file_unique_id, file_name=:file_name, mime_type=:mime_type,
                    error_public=NULL, updated_at=:updated_at
                WHERE session_ref=:session_ref
                """
            ),
            {
                "texto": texto,
                "media_kind": kind,
                "file_id": file_id or None,
                "file_unique_id": _safe_text(message_data.get("file_unique_id"), fallback="")[:260] or None,
                "file_name": _safe_text(message_data.get("file_name"), fallback="")[:180] or None,
                "mime_type": _safe_text(message_data.get("mime_type"), fallback="")[:120] or None,
                "updated_at": _now_iso(),
                "session_ref": str(session["session_ref"]),
            },
        )
    return public_multimedia_session(get_multimedia_session(session_ref=str(session["session_ref"]), db_engine=db_engine))


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
    return "sendMessage", "text", None


async def publish_multimedia_session(*, palco: dict[str, object], ator_ref: str, session_ref: str, bot_token: str, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    session = get_multimedia_session(session_ref=session_ref, db_engine=db_engine)
    if str(session.get("palco_ref")) != str(palco["ui_ref"]):
        raise MultimediaError("Sessão fora do grupo selecionado.")
    if str(session.get("status")) != "ready":
        raise MultimediaError("Envie a mídia ou texto no privado do bot antes de publicar.")
    kind = str(session.get("media_kind") or "text")
    method, field_name, required_right = _method_for_kind(kind)
    chat_id = int(palco["telegram_chat_id"])
    await ensure_bot_right(bot_token=bot_token, chat_id=chat_id, required_right=required_right)
    texto = str(session.get("texto") or "")
    if kind == "text":
        if not texto.strip():
            raise MultimediaError("Mensagem vazia.")
        payload: dict[str, Any] = {"chat_id": chat_id, "text": texto[:4096], "disable_web_page_preview": True}
    else:
        file_id = str(session.get("file_id") or "")
        if not file_id:
            raise MultimediaError("Arquivo da sessão indisponível.")
        payload = {"chat_id": chat_id, field_name: file_id, "caption": texto[:1024] if texto else None}
    try:
        result = await telegram_api_call(bot_token, method, payload)
    except MesaError as exc:
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE eq_multimedia_sessions SET status='failed', error_public=:error, updated_at=:updated_at WHERE session_ref=:ref"),
                {"error": _safe_text(exc, fallback="Telegram recusou a publicação."), "updated_at": _now_iso(), "ref": str(session_ref)},
            )
        raise
    if not isinstance(result, dict) or not result.get("message_id"):
        raise MultimediaError("Telegram não retornou a mensagem publicada.")
    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=int(result["message_id"]),
        resumo_publico=_safe_text(texto, fallback="Publicação multimídia"),
        alias_secret=alias_secret,
        message_unix_time=int(result.get("date") or 0) or None,
        db_engine=db_engine,
    )
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_multimedia_sessions SET status='published', msg_ref=:msg_ref, updated_at=:updated_at WHERE session_ref=:ref"),
            {"msg_ref": msg_ref, "updated_at": now, "ref": str(session_ref)},
        )
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=str(palco["ui_ref"]),
        alvo_ref=msg_ref,
        ajuste="multimidia.publicar",
        status="ok",
        resumo_publico="Publicação multimídia enviada pelo bot.",
        payload_tecnico={"tipo": kind},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {"ok": True, "sessao": public_multimedia_session(get_multimedia_session(session_ref=session_ref, db_engine=db_engine)), "mensagem": {"msg_ref": msg_ref}, "historico": historico}
