from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref, public_tme_url, safe_public_username, display_name_from_telegram_user
from app.equalizador.mesa import (
    MesaError,
    MesaNotFoundError,
    MesaRightError,
    MesaTargetError,
    _safe_error_text,
    _safe_text,
    ensure_bot_right,
    ensure_phase5_tables,
    record_historico,
    register_alvo_ref,
    register_mensagem_ref,
    resolve_alvo_ref,
    telegram_api_call as mesa_telegram_api_call,
)
from app.equalizador.avancado import register_sender_chat_ref, resolve_sender_ref, ensure_phase44_tables

TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


class ReacoesError(MesaError):
    """Raised when a reaction audit/action cannot be completed."""


class ReacoesNotFoundError(ReacoesError):
    """Raised when a reaction reference is unavailable."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: object, fallback: object) -> object:
    try:
        return json.loads(str(value or ""))
    except Exception:
        return fallback


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(str(value or "").strip() or default)
    except (TypeError, ValueError):
        return int(default)


def _reaction_label(item: object) -> str:
    if isinstance(item, dict):
        kind = str(item.get("type") or "").strip()
        if kind == "emoji":
            return str(item.get("emoji") or "emoji")[:24]
        if kind == "custom_emoji":
            return "emoji personalizado"
        if kind == "paid":
            return "reação paga"
        return kind or "reação"
    return _safe_text(item, fallback="reação")[:32]


def _reaction_summary(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "sem reação"
    labels = [_reaction_label(item) for item in items[:6]]
    extra = len(items) - len(labels)
    return " · ".join(labels) + (f" +{extra}" if extra > 0 else "")


def _reaction_count(items: object) -> int:
    return len(items) if isinstance(items, list) else 0


def _event_ref(*, chat_id: int, message_id: int, actor_key: str, date: int, alias_secret: str) -> str:
    return "rea_" + make_ui_ref("grp", f"reaction:{int(chat_id)}:{int(message_id)}:{actor_key}:{int(date)}", alias_secret).split("_", 1)[1]


def _recent_ref(*, chat_id: int, actor_key: str, alias_secret: str) -> str:
    return "rct_" + make_ui_ref("grp", f"reactor:{int(chat_id)}:{actor_key}", alias_secret).split("_", 1)[1]


def ensure_reacoes_tables(db_engine: Engine = default_engine) -> None:
    ensure_phase5_tables(db_engine)
    ensure_phase44_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_reaction_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_ref TEXT NOT NULL UNIQUE,
                telegram_chat_id INTEGER NOT NULL,
                palco_ref TEXT NOT NULL,
                telegram_message_id INTEGER NOT NULL,
                msg_ref TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                actor_ref TEXT NOT NULL,
                actor_label TEXT NOT NULL,
                username TEXT,
                old_reactions_json TEXT NOT NULL,
                new_reactions_json TEXT NOT NULL,
                old_summary TEXT NOT NULL,
                new_summary TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_reaction_recent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recent_ref TEXT NOT NULL UNIQUE,
                telegram_chat_id INTEGER NOT NULL,
                palco_ref TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                actor_ref TEXT NOT NULL,
                actor_label TEXT NOT NULL,
                username TEXT,
                last_msg_ref TEXT,
                last_summary TEXT,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                silenciado_ate TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (telegram_chat_id, actor_ref)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_reaction_events_palco ON eq_reaction_events(palco_ref, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_reaction_recent_palco ON eq_reaction_recent(palco_ref, last_seen_at)"))


def _palco_for_chat_id(chat_id: int, *, alias_secret: str, db_engine: Engine) -> dict[str, object] | None:
    ensure_reacoes_tables(db_engine)
    if chat_id not in settings.equalizador_allowed_palco_ids():
        return None
    ui_ref = make_ui_ref("grp", int(chat_id), alias_secret)
    with db_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT telegram_chat_id, ui_ref, titulo, username
            FROM eq_palcos
            WHERE telegram_chat_id=:chat_id AND habilitado=1
            LIMIT 1
        """), {"chat_id": int(chat_id)}).mappings().first()
        if row:
            return dict(row)
        # Fallback seguro para webhook antes da primeira abertura do Mini App.
        conn.execute(text("""
            INSERT INTO eq_palcos (telegram_chat_id, username, titulo, ui_label, ui_ref, habilitado, updated_at)
            VALUES (:chat_id, NULL, :titulo, :titulo, :ui_ref, 1, :updated_at)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET ui_ref=excluded.ui_ref, habilitado=1, updated_at=excluded.updated_at
        """), {"chat_id": int(chat_id), "titulo": settings.group_alias_for_chat(chat_id) or "Grupo", "ui_ref": ui_ref, "updated_at": _now_iso()})
    return {"telegram_chat_id": int(chat_id), "ui_ref": ui_ref, "titulo": settings.group_alias_for_chat(chat_id) or "Grupo", "username": ""}


def _actor_from_reaction(payload: dict[str, Any], *, chat_id: int, alias_secret: str, db_engine: Engine) -> tuple[str, str, str, str | None]:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else None
    actor_chat = payload.get("actor_chat") if isinstance(payload.get("actor_chat"), dict) else None
    if user:
        user_id = _safe_int(user.get("id"))
        if user_id <= 0:
            raise ReacoesError("autor_reacao_indisponivel")
        label = display_name_from_telegram_user(user, fallback="Participante")
        username = safe_public_username(user.get("username")) or None
        actor_ref = register_alvo_ref(
            chat_id=int(chat_id),
            user_id=int(user_id),
            nome_publico=label,
            alias_secret=alias_secret,
            username=username,
            telegram_status="reaction_actor",
            db_engine=db_engine,
        )
        return "user", actor_ref, label, username
    if actor_chat:
        sender_chat_id = _safe_int(actor_chat.get("id"))
        if sender_chat_id == 0:
            raise ReacoesError("canal_reacao_indisponivel")
        label = _safe_text(actor_chat.get("title") or actor_chat.get("first_name") or actor_chat.get("username"), fallback="Canal remetente")
        username = safe_public_username(actor_chat.get("username")) or None
        actor_ref = register_sender_chat_ref(
            chat_id=int(chat_id),
            sender_chat_id=int(sender_chat_id),
            titulo_publico=label,
            username=username,
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return "sender_chat", actor_ref, label, username
    raise ReacoesError("autor_reacao_indisponivel")


def _public_reaction_row(row: dict[str, Any]) -> dict[str, object]:
    username = safe_public_username(row.get("username"))
    return {
        "event_ref": str(row.get("event_ref") or ""),
        "msg_ref": str(row.get("msg_ref") or ""),
        "actor_kind": str(row.get("actor_kind") or "user"),
        "actor_ref": str(row.get("actor_ref") or ""),
        "nome": _safe_text(row.get("actor_label"), fallback="Participante"),
        "username": username,
        "contato_url": public_tme_url(username),
        "old_summary": _safe_text(row.get("old_summary"), fallback="sem reação"),
        "new_summary": _safe_text(row.get("new_summary"), fallback="sem reação"),
        "status": _safe_text(row.get("status"), fallback="registrado"),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _public_recent_row(row: dict[str, Any]) -> dict[str, object]:
    username = safe_public_username(row.get("username"))
    return {
        "recent_ref": str(row.get("recent_ref") or ""),
        "actor_kind": str(row.get("actor_kind") or "user"),
        "actor_ref": str(row.get("actor_ref") or ""),
        "nome": _safe_text(row.get("actor_label"), fallback="Participante"),
        "username": username,
        "contato_url": public_tme_url(username),
        "last_msg_ref": str(row.get("last_msg_ref") or ""),
        "last_summary": _safe_text(row.get("last_summary"), fallback="sem reação"),
        "last_seen_at": str(row.get("last_seen_at") or ""),
        "seen_count": _safe_int(row.get("seen_count"), default=0),
        "silenciado_ate": str(row.get("silenciado_ate") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def record_reaction_update_payload(
    update_payload: dict[str, Any],
    *,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> bool:
    """Persist Telegram message_reaction updates as sanitized audit entries.

    The raw Telegram numeric identifiers remain server-side. The UI receives only
    refs such as ``msg_...`` and ``usr_...``/``snd_...``.
    """
    reaction = update_payload.get("message_reaction") if isinstance(update_payload, dict) else None
    if not isinstance(reaction, dict):
        return False
    chat = reaction.get("chat") if isinstance(reaction.get("chat"), dict) else {}
    chat_id = _safe_int(chat.get("id"))
    message_id = _safe_int(reaction.get("message_id"))
    if chat_id == 0 or message_id <= 0:
        return False
    palco = _palco_for_chat_id(chat_id, alias_secret=alias_secret, db_engine=db_engine)
    if not palco:
        return False
    date_value = _safe_int(reaction.get("date"), default=_now_unix())
    actor_kind, actor_ref, actor_label, username = _actor_from_reaction(reaction, chat_id=chat_id, alias_secret=alias_secret, db_engine=db_engine)
    old_reactions = reaction.get("old_reaction") if isinstance(reaction.get("old_reaction"), list) else []
    new_reactions = reaction.get("new_reaction") if isinstance(reaction.get("new_reaction"), list) else []
    status = "adicionou" if _reaction_count(new_reactions) > _reaction_count(old_reactions) else "removeu"
    if _reaction_count(new_reactions) == _reaction_count(old_reactions):
        status = "alterou"
    msg_ref = register_mensagem_ref(
        chat_id=chat_id,
        message_id=message_id,
        resumo_publico=f"Mensagem com reação · {_safe_text(actor_label, fallback='Participante')}",
        alias_secret=alias_secret,
        message_unix_time=date_value,
        db_engine=db_engine,
    )
    actor_key = f"{actor_kind}:{actor_ref}"
    event_ref = _event_ref(chat_id=chat_id, message_id=message_id, actor_key=actor_key, date=date_value, alias_secret=alias_secret)
    recent_ref = _recent_ref(chat_id=chat_id, actor_key=actor_key, alias_secret=alias_secret)
    old_summary = _reaction_summary(old_reactions)
    new_summary = _reaction_summary(new_reactions)
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(text("""
            INSERT OR IGNORE INTO eq_reaction_events (
                event_ref, telegram_chat_id, palco_ref, telegram_message_id, msg_ref,
                actor_kind, actor_ref, actor_label, username,
                old_reactions_json, new_reactions_json, old_summary, new_summary,
                status, created_at, updated_at
            ) VALUES (
                :event_ref, :chat_id, :palco_ref, :message_id, :msg_ref,
                :actor_kind, :actor_ref, :actor_label, :username,
                :old_json, :new_json, :old_summary, :new_summary,
                :status, :created_at, :updated_at
            )
        """), {
            "event_ref": event_ref,
            "chat_id": int(chat_id),
            "palco_ref": str(palco["ui_ref"]),
            "message_id": int(message_id),
            "msg_ref": msg_ref,
            "actor_kind": actor_kind,
            "actor_ref": actor_ref,
            "actor_label": _safe_text(actor_label, fallback="Participante"),
            "username": username,
            "old_json": _json_dumps(old_reactions),
            "new_json": _json_dumps(new_reactions),
            "old_summary": old_summary,
            "new_summary": new_summary,
            "status": status,
            "created_at": datetime.fromtimestamp(date_value, tz=timezone.utc).isoformat(),
            "updated_at": now,
        })
        conn.execute(text("""
            INSERT INTO eq_reaction_recent (
                recent_ref, telegram_chat_id, palco_ref, actor_kind, actor_ref, actor_label, username,
                last_msg_ref, last_summary, last_seen_at, seen_count, silenciado_ate, updated_at
            ) VALUES (
                :recent_ref, :chat_id, :palco_ref, :actor_kind, :actor_ref, :actor_label, :username,
                :last_msg_ref, :last_summary, :last_seen_at, 1, NULL, :updated_at
            )
            ON CONFLICT(telegram_chat_id, actor_ref) DO UPDATE SET
                recent_ref=excluded.recent_ref,
                actor_kind=excluded.actor_kind,
                actor_label=excluded.actor_label,
                username=COALESCE(excluded.username, eq_reaction_recent.username),
                last_msg_ref=excluded.last_msg_ref,
                last_summary=excluded.last_summary,
                last_seen_at=excluded.last_seen_at,
                seen_count=eq_reaction_recent.seen_count + 1,
                updated_at=excluded.updated_at
        """), {
            "recent_ref": recent_ref,
            "chat_id": int(chat_id),
            "palco_ref": str(palco["ui_ref"]),
            "actor_kind": actor_kind,
            "actor_ref": actor_ref,
            "actor_label": _safe_text(actor_label, fallback="Participante"),
            "username": username,
            "last_msg_ref": msg_ref,
            "last_summary": new_summary,
            "last_seen_at": datetime.fromtimestamp(date_value, tz=timezone.utc).isoformat(),
            "updated_at": now,
        })
    return True


def list_reacoes_publicas(
    *,
    palco: dict[str, object],
    db_engine: Engine = default_engine,
    limit: int = 80,
) -> dict[str, object]:
    ensure_reacoes_tables(db_engine)
    palco_ref = str(palco.get("ui_ref") or "")
    chat_id = int(palco.get("telegram_chat_id") or 0)
    with db_engine.begin() as conn:
        eventos = conn.execute(text("""
            SELECT * FROM eq_reaction_events
            WHERE telegram_chat_id=:chat_id AND palco_ref=:palco_ref
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
        """), {"chat_id": chat_id, "palco_ref": palco_ref, "limit": int(limit)}).mappings().all()
        recentes = conn.execute(text("""
            SELECT * FROM eq_reaction_recent
            WHERE telegram_chat_id=:chat_id AND palco_ref=:palco_ref
            ORDER BY last_seen_at DESC, id DESC
            LIMIT :limit
        """), {"chat_id": chat_id, "palco_ref": palco_ref, "limit": int(limit)}).mappings().all()
    return {
        "eventos": [_public_reaction_row(dict(row)) for row in eventos],
        "recentes": [_public_recent_row(dict(row)) for row in recentes],
        "resumo": {
            "eventos": len(eventos),
            "reactors_recentes": len(recentes),
            "observacao": "A auditoria depende de updates message_reaction enviados pelo Telegram ao webhook.",
        },
    }


def _resolve_recent_ref(*, palco_id: int, recent_ref: str, db_engine: Engine) -> dict[str, Any]:
    ensure_reacoes_tables(db_engine)
    ref = str(recent_ref or "").strip()
    if not ref.startswith("rct_"):
        raise ReacoesNotFoundError("reactor_indisponivel")
    with db_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT * FROM eq_reaction_recent
            WHERE telegram_chat_id=:chat_id AND recent_ref=:recent_ref
            LIMIT 1
        """), {"chat_id": int(palco_id), "recent_ref": ref}).mappings().first()
    if not row:
        raise ReacoesNotFoundError("reactor_indisponivel")
    return dict(row)


def _duration_until(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=max(1, min(10080, int(minutes))))).isoformat()


async def silenciar_reactor(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = mesa_telegram_api_call,
) -> dict[str, object]:
    """Apply a conservative interaction mute to a recent reaction actor.

    Telegram Bot API does not expose a per-user "can react" flag in every
    deployment. The action therefore preserves basic text/media permissions and
    disables ``can_send_other_messages`` as the narrowest generally available
    interaction control. The UI presents this as best-effort and keeps IDs hidden.
    """
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    recent_ref = _safe_text(payload.get("recent_ref"))
    minutes = max(1, min(10080, _safe_int(payload.get("duracao_minutos"), default=60)))
    recent = _resolve_recent_ref(palco_id=palco_id, recent_ref=recent_ref, db_engine=db_engine)
    if str(recent.get("actor_kind")) != "user":
        raise MesaTargetError("Apenas usuários podem ser silenciados por permissão individual.")
    actor_ref = str(recent.get("actor_ref") or "")
    target = resolve_alvo_ref(palco_id=palco_id, alvo_ref=actor_ref, db_engine=db_engine)
    until_date = _now_unix() + minutes * 60
    label = _safe_text(recent.get("actor_label"), fallback="Participante")
    telegram_payload = {
        "chat_id": palco_id,
        "user_id": int(target["telegram_user_id"]),
        "until_date": int(until_date),
        "permissions": {
            "can_send_messages": True,
            "can_send_audios": True,
            "can_send_documents": True,
            "can_send_photos": True,
            "can_send_videos": True,
            "can_send_video_notes": True,
            "can_send_voice_notes": True,
            "can_send_polls": True,
            "can_send_other_messages": False,
            "can_add_web_page_previews": True,
            "can_invite_users": True,
        },
    }
    try:
        await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right="can_restrict_members", telegram_api_call=telegram_api_call)
        await telegram_api_call(bot_token, "restrictChatMember", telegram_payload)
        silenciado_ate = datetime.fromtimestamp(until_date, tz=timezone.utc).isoformat()
        with db_engine.begin() as conn:
            conn.execute(text("""
                UPDATE eq_reaction_recent
                SET silenciado_ate=:silenciado_ate, updated_at=:updated_at
                WHERE telegram_chat_id=:chat_id AND recent_ref=:recent_ref
            """), {"silenciado_ate": silenciado_ate, "updated_at": _now_iso(), "chat_id": palco_id, "recent_ref": recent_ref})
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=actor_ref,
            ajuste="reacoes.reactor.silenciar",
            status="concluido",
            resumo_publico=f"Reactor silenciado: {label}",
            payload_tecnico={"method": "restrictChatMember", "duracao_minutos": minutes, "modo": "best_effort_interaction_mute"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {
            "ok": True,
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
            "resultado": {"nome": label, "estado": "silenciado", "silenciado_ate": silenciado_ate},
        }
    except Exception as exc:
        detail = reacoes_error_public_detail(exc)
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=actor_ref,
            ajuste="reacoes.reactor.silenciar",
            status="falhou",
            resumo_publico=f"Silenciar reactor não concluído · {detail}",
            payload_tecnico={"erro": _safe_error_text(exc, fallback=exc.__class__.__name__), "motivo_publico": detail, "method": "restrictChatMember"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MesaError):
            raise
        raise ReacoesError("Silenciar reactor não concluído.") from exc


def reacoes_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, MesaRightError):
        return "Permissão real do bot insuficiente."
    if isinstance(exc, (MesaNotFoundError, ReacoesNotFoundError)):
        return "Referência indisponível."
    if isinstance(exc, MesaTargetError):
        return _safe_error_text(getattr(exc, "description", str(exc)), fallback="Alvo indisponível.")
    if isinstance(exc, MesaError):
        return _safe_error_text(exc, fallback="Operação de reações não concluída.")
    return _safe_error_text(exc, fallback="Operação de reações não concluída.")
