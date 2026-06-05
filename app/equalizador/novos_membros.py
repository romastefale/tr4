from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.identity import display_name_from_telegram_user, make_ui_ref, public_tme_url, safe_public_username
from app.equalizador.mesa import ensure_phase5_tables, register_alvo_ref, register_mensagem_ref
from app.equalizador.palcos import ensure_equalizador_tables

logger = logging.getLogger(__name__)

WATCH_TTL_HOURS = 48
MAX_WATCH_MESSAGES = 8
MAX_EVENTS = 80
MAX_RECENT = 80

_LINK_RE = re.compile(
    r"(?i)(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|br|app|dev|site|online|xyz|info|me|co)(?:/\S*)?)"
)


class NovosMembrosError(RuntimeError):
    pass


class NovosMembrosNotFoundError(NovosMembrosError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = re.sub(r"\s+", " ", str(value or "").strip())
    return text_value[:240] or fallback


def _safe_preview(value: object, *, limit: int = 180) -> str:
    text_value = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "…"


def _prefix_ref(prefix: str, seed: str, alias_secret: str) -> str:
    return prefix + "_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def _watch_ref(*, palco_ref: str, alvo_ref: str, alias_secret: str) -> str:
    return _prefix_ref("nmw", f"new-member-watch:{palco_ref}:{alvo_ref}", alias_secret)


def _event_ref(*, palco_ref: str, alvo_ref: str, msg_ref: str, created_at: str, alias_secret: str) -> str:
    return _prefix_ref("nme", f"new-member-event:{palco_ref}:{alvo_ref}:{msg_ref}:{created_at}", alias_secret)


def _clean_links(text_value: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in _LINK_RE.findall(str(text_value or "")):
        value = str(match).strip().rstrip(r".,;:!?)\]}>")
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        links.append(value[:140])
        if len(links) >= 5:
            break
    return links


def ensure_novos_membros_tables(db_engine: Engine = default_engine) -> None:
    ensure_equalizador_tables(db_engine)
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_join_window (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    alvo_ref TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_username TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    messages_seen INTEGER NOT NULL DEFAULT 0,
                    joined_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_chat_id, alvo_ref)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_join_window_palco ON eq_join_window(palco_ref, status, updated_at)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_new_member_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    telegram_chat_id INTEGER NOT NULL,
                    palco_ref TEXT NOT NULL,
                    watch_ref TEXT,
                    alvo_ref TEXT NOT NULL,
                    msg_ref TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    actor_name TEXT NOT NULL,
                    actor_username TEXT,
                    links_json TEXT NOT NULL DEFAULT '[]',
                    text_preview TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_new_member_events_palco ON eq_new_member_events(palco_ref, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_new_member_events_status ON eq_new_member_events(event_ref, status)"))


def _public_person(name: object, username: object) -> dict[str, object]:
    safe_username = safe_public_username(username)
    return {
        "nome": _safe_text(name, fallback="Membro"),
        "username": safe_username,
        "contato_url": public_tme_url(safe_username),
    }


def _watch_public(row: dict[str, Any]) -> dict[str, object]:
    person = _public_person(row.get("actor_name"), row.get("actor_username"))
    return {
        "watch_ref": str(row.get("watch_ref") or ""),
        "alvo_ref": str(row.get("alvo_ref") or ""),
        "status": str(row.get("status") or "active"),
        "mensagens_vistas": int(row.get("messages_seen") or 0),
        "joined_at": str(row.get("joined_at") or ""),
        "expires_at": str(row.get("expires_at") or ""),
        **person,
    }


def _event_public(row: dict[str, Any]) -> dict[str, object]:
    person = _public_person(row.get("actor_name"), row.get("actor_username"))
    try:
        links = json.loads(str(row.get("links_json") or "[]"))
    except Exception:
        links = []
    return {
        "event_ref": str(row.get("event_ref") or ""),
        "watch_ref": str(row.get("watch_ref") or ""),
        "alvo_ref": str(row.get("alvo_ref") or ""),
        "msg_ref": str(row.get("msg_ref") or ""),
        "status": str(row.get("status") or "pending"),
        "links": [str(link) for link in links if str(link).strip()][:5],
        "preview": str(row.get("text_preview") or ""),
        "created_at": str(row.get("created_at") or ""),
        **person,
    }


def list_novos_membros_publicos(*, palco: dict[str, object], db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_novos_membros_tables(db_engine)
    palco_ref = str(palco.get("ui_ref") or "")
    with db_engine.begin() as conn:
        recent_rows = conn.execute(
            text(
                """
                SELECT watch_ref, alvo_ref, actor_name, actor_username, status, messages_seen, joined_at, expires_at, updated_at
                FROM eq_join_window
                WHERE palco_ref=:palco_ref
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"palco_ref": palco_ref, "limit": MAX_RECENT},
        ).mappings().all()
        event_rows = conn.execute(
            text(
                """
                SELECT event_ref, watch_ref, alvo_ref, msg_ref, status, actor_name, actor_username, links_json, text_preview, created_at
                FROM eq_new_member_events
                WHERE palco_ref=:palco_ref
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"palco_ref": palco_ref, "limit": MAX_EVENTS},
        ).mappings().all()
    recentes = [_watch_public(dict(row)) for row in recent_rows]
    eventos = [_event_public(dict(row)) for row in event_rows]
    return {
        "recentes": recentes,
        "eventos": eventos,
        "resumo": {
            "monitorados": len(recentes),
            "ativos": sum(1 for row in recentes if row.get("status") == "active"),
            "alertas_pendentes": sum(1 for row in eventos if row.get("status") == "pending"),
        },
        "observacao": "Observa recém-chegados por janela curta e alerta quando há link nas primeiras mensagens.",
    }


def get_new_member_event(*, palco: dict[str, object], event_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_novos_membros_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT event_ref, watch_ref, alvo_ref, msg_ref, status, actor_name, actor_username, links_json, text_preview, created_at
                FROM eq_new_member_events
                WHERE palco_ref=:palco_ref AND event_ref=:event_ref
                LIMIT 1
                """
            ),
            {"palco_ref": str(palco.get("ui_ref") or ""), "event_ref": str(event_ref)},
        ).mappings().first()
    if not row:
        raise NovosMembrosNotFoundError("alerta_indisponivel")
    return dict(row)


def marcar_new_member_event(
    *,
    palco: dict[str, object],
    event_ref: str,
    status: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_novos_membros_tables(db_engine)
    safe_status = str(status or "handled").strip()[:32] or "handled"
    now = _now_iso()
    with db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE eq_new_member_events
                SET status=:status, updated_at=:updated_at
                WHERE palco_ref=:palco_ref AND event_ref=:event_ref
                """
            ),
            {"status": safe_status, "updated_at": now, "palco_ref": str(palco.get("ui_ref") or ""), "event_ref": str(event_ref)},
        )
    if result.rowcount == 0:
        raise NovosMembrosNotFoundError("alerta_indisponivel")
    return {"ok": True, "event_ref": str(event_ref), "status": safe_status, "resumo": "Alerta atualizado."}


def _telegram_user_dict(user: Any) -> dict[str, object]:
    return {
        "id": int(getattr(user, "id", 0) or 0),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "username": getattr(user, "username", None),
        "is_bot": bool(getattr(user, "is_bot", False)),
    }


def _message_text(message: Any) -> str:
    return str(getattr(message, "text", None) or getattr(message, "caption", None) or "")


def _message_id(message: Any) -> int:
    return int(getattr(message, "message_id", 0) or 0)


def _message_date_unix(message: Any) -> int | None:
    date_value = getattr(message, "date", None)
    if hasattr(date_value, "timestamp"):
        try:
            return int(date_value.timestamp())
        except Exception:
            return None
    try:
        return int(date_value or 0) or None
    except Exception:
        return None


def _palco_from_chat_id(chat_id: int, alias_secret: str) -> dict[str, object] | None:
    if int(chat_id) not in settings.equalizador_allowed_palco_ids():
        return None
    return {"telegram_chat_id": int(chat_id), "ui_ref": make_ui_ref("grp", int(chat_id), alias_secret), "titulo": settings.group_alias_for_chat(int(chat_id)) or "Grupo"}


def _register_new_member(*, chat_id: int, user: Any, alias_secret: str, db_engine: Engine) -> dict[str, object] | None:
    user_data = _telegram_user_dict(user)
    user_id = int(user_data.get("id") or 0)
    if user_id <= 0:
        return None
    palco = _palco_from_chat_id(chat_id, alias_secret)
    if not palco:
        return None
    nome = display_name_from_telegram_user(user_data, fallback="Membro")
    alvo_ref = register_alvo_ref(
        chat_id=int(chat_id),
        user_id=user_id,
        nome_publico=nome,
        username=str(user_data.get("username") or "") or None,
        telegram_status="novos_membros",
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    now = _now()
    expires_at = (now + timedelta(hours=WATCH_TTL_HOURS)).isoformat()
    watch_ref = _watch_ref(palco_ref=str(palco["ui_ref"]), alvo_ref=alvo_ref, alias_secret=alias_secret)
    ensure_novos_membros_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_join_window (
                    watch_ref, telegram_chat_id, palco_ref, alvo_ref, actor_name, actor_username, status,
                    messages_seen, joined_at, expires_at, updated_at
                ) VALUES (
                    :watch_ref, :telegram_chat_id, :palco_ref, :alvo_ref, :actor_name, :actor_username, 'active',
                    0, :joined_at, :expires_at, :updated_at
                )
                ON CONFLICT(telegram_chat_id, alvo_ref) DO UPDATE SET
                    watch_ref=excluded.watch_ref,
                    actor_name=excluded.actor_name,
                    actor_username=COALESCE(excluded.actor_username, eq_join_window.actor_username),
                    status='active',
                    messages_seen=0,
                    joined_at=excluded.joined_at,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "watch_ref": watch_ref,
                "telegram_chat_id": int(chat_id),
                "palco_ref": str(palco["ui_ref"]),
                "alvo_ref": alvo_ref,
                "actor_name": nome,
                "actor_username": safe_public_username(user_data.get("username")) or None,
                "joined_at": now.isoformat(),
                "expires_at": expires_at,
                "updated_at": now.isoformat(),
            },
        )
    return {"watch_ref": watch_ref, "alvo_ref": alvo_ref, "nome": nome, "username": safe_public_username(user_data.get("username"))}


def _active_watch_for_user(*, chat_id: int, user_id: int, alias_secret: str, db_engine: Engine) -> dict[str, object] | None:
    palco = _palco_from_chat_id(chat_id, alias_secret)
    if not palco:
        return None
    alvo_ref = make_ui_ref("usr", f"{int(chat_id)}:{int(user_id)}", alias_secret)
    now_iso = _now_iso()
    ensure_novos_membros_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT watch_ref, palco_ref, alvo_ref, actor_name, actor_username, status, messages_seen, expires_at
                FROM eq_join_window
                WHERE telegram_chat_id=:chat_id AND alvo_ref=:alvo_ref
                LIMIT 1
                """
            ),
            {"chat_id": int(chat_id), "alvo_ref": alvo_ref},
        ).mappings().first()
        if not row:
            return None
        row_dict = dict(row)
        status = str(row_dict.get("status") or "active")
        messages_seen = int(row_dict.get("messages_seen") or 0)
        expired = str(row_dict.get("expires_at") or "") <= now_iso or messages_seen >= MAX_WATCH_MESSAGES
        if status != "active" or expired:
            conn.execute(
                text("UPDATE eq_join_window SET status='expired', updated_at=:updated_at WHERE telegram_chat_id=:chat_id AND alvo_ref=:alvo_ref AND status='active'"),
                {"updated_at": now_iso, "chat_id": int(chat_id), "alvo_ref": alvo_ref},
            )
            return None
        conn.execute(
            text("UPDATE eq_join_window SET messages_seen=messages_seen+1, updated_at=:updated_at WHERE telegram_chat_id=:chat_id AND alvo_ref=:alvo_ref"),
            {"updated_at": now_iso, "chat_id": int(chat_id), "alvo_ref": alvo_ref},
        )
    return row_dict


async def _notify_maestros(bot: Any, *, chat_title: str, actor_name: str, actor_username: str | None, links: list[str], preview: str) -> None:
    if not bot or not settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET:
        return
    username_line = f"@{html.escape(actor_username)}" if actor_username else "sem @username público"
    links_line = ", ".join(html.escape(link) for link in links[:3])
    text_value = (
        "Equalizador · novo membro com link\n\n"
        f"Grupo: {html.escape(_safe_text(chat_title, fallback='Grupo'))}\n"
        f"Membro: {html.escape(actor_name)} · {username_line}\n"
        f"Links: {links_line or 'link detectado'}\n"
        f"Prévia: {html.escape(_safe_preview(preview, limit=180))}"
    )
    for maestro_id in sorted(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET):
        try:
            await bot.send_message(chat_id=int(maestro_id), text=text_value, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.debug("NOVOS_MEMBROS_NOTIFY_FAILED", exc_info=True)


async def equalizador_novos_membros_preprocess_update(
    bot: Any,
    update: Any,
    *,
    alias_secret: str | None = None,
    db_engine: Engine = default_engine,
) -> None:
    """Observe new group members and flag links in their first messages.

    This function never consumes the update. It only records sanitized events and
    alerts the configured maestros. Moderation actions are done later in the UI.
    """
    secret = alias_secret or settings.equalizador_alias_secret()
    message = getattr(update, "message", None)
    if not message or not getattr(message, "chat", None):
        return
    chat = message.chat
    chat_id = int(getattr(chat, "id", 0) or 0)
    chat_type = str(getattr(chat, "type", "") or "")
    if chat_id == 0 or chat_type not in {"group", "supergroup"}:
        return
    if chat_id not in settings.equalizador_allowed_palco_ids():
        return

    new_members = list(getattr(message, "new_chat_members", None) or [])
    for user in new_members:
        _register_new_member(chat_id=chat_id, user=user, alias_secret=secret, db_engine=db_engine)
    if new_members:
        return

    user = getattr(message, "from_user", None)
    user_id = int(getattr(user, "id", 0) or 0) if user else 0
    if user_id <= 0:
        return
    watch = _active_watch_for_user(chat_id=chat_id, user_id=user_id, alias_secret=secret, db_engine=db_engine)
    if not watch:
        return
    text_value = _message_text(message)
    links = _clean_links(text_value)
    if not links:
        return

    user_data = _telegram_user_dict(user)
    actor_name = display_name_from_telegram_user(user_data, fallback=str(watch.get("actor_name") or "Membro"))
    actor_username = safe_public_username(user_data.get("username")) or safe_public_username(watch.get("actor_username")) or None
    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=_message_id(message),
        resumo_publico=f"Novo membro com link: {_safe_preview(text_value, limit=70)}",
        alias_secret=secret,
        message_unix_time=_message_date_unix(message),
        db_engine=db_engine,
    )
    created_at = _now_iso()
    event_ref = _event_ref(palco_ref=str(watch["palco_ref"]), alvo_ref=str(watch["alvo_ref"]), msg_ref=msg_ref, created_at=created_at, alias_secret=secret)
    ensure_novos_membros_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_new_member_events (
                    event_ref, telegram_chat_id, palco_ref, watch_ref, alvo_ref, msg_ref, status,
                    actor_name, actor_username, links_json, text_preview, created_at, updated_at
                ) VALUES (
                    :event_ref, :telegram_chat_id, :palco_ref, :watch_ref, :alvo_ref, :msg_ref, 'pending',
                    :actor_name, :actor_username, :links_json, :text_preview, :created_at, :updated_at
                )
                ON CONFLICT(event_ref) DO NOTHING
                """
            ),
            {
                "event_ref": event_ref,
                "telegram_chat_id": chat_id,
                "palco_ref": str(watch["palco_ref"]),
                "watch_ref": str(watch["watch_ref"]),
                "alvo_ref": str(watch["alvo_ref"]),
                "msg_ref": msg_ref,
                "actor_name": actor_name,
                "actor_username": actor_username,
                "links_json": json.dumps(links, ensure_ascii=False),
                "text_preview": _safe_preview(text_value),
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
    await _notify_maestros(
        bot,
        chat_title=str(getattr(chat, "title", "") or "Grupo"),
        actor_name=actor_name,
        actor_username=actor_username,
        links=links,
        preview=text_value,
    )
    logger.info("EQUALIZADOR_NEW_MEMBER_LINK_DETECTED | palco=%s | event=%s", watch.get("palco_ref"), event_ref)


def novos_membros_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, NovosMembrosNotFoundError):
        return "Alerta de novo membro indisponível."
    return "Ação de monitoramento de novo membro não concluída."
