from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.afinacao import fetch_bot_member_rights
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables


class MesaError(RuntimeError):
    """Raised when a Mesa adjustment cannot be executed."""


class MesaNotFoundError(MesaError):
    """Raised when a public alias cannot be resolved internally."""


class MesaRightError(MesaError):
    """Raised when the bot lacks the real Telegram right required."""


@dataclass(frozen=True)
class MesaActionSpec:
    ajuste: str
    canal_codigo: str
    telegram_method: str
    direito: str | None
    target_kind: str


ACTION_SPECS: dict[str, MesaActionSpec] = {
    "mensagens.apagar": MesaActionSpec("mensagens.apagar", "mensagens.apagar", "deleteMessage", "can_delete_messages", "mensagem"),
    "membros.silenciar": MesaActionSpec("membros.silenciar", "membros.silenciar", "restrictChatMember", "can_restrict_members", "alvo"),
    "membros.liberar": MesaActionSpec("membros.liberar", "membros.liberar", "restrictChatMember", "can_restrict_members", "alvo"),
    "membros.remover": MesaActionSpec("membros.remover", "membros.remover", "banChatMember", "can_restrict_members", "alvo"),
    "membros.reintegrar": MesaActionSpec("membros.reintegrar", "membros.reintegrar", "unbanChatMember", "can_restrict_members", "alvo"),
    "fixados.criar": MesaActionSpec("fixados.criar", "fixados.criar", "pinChatMessage", "can_pin_messages", "mensagem"),
    "fixados.remover": MesaActionSpec("fixados.remover", "fixados.remover", "unpinChatMessage", "can_pin_messages", "mensagem"),
    "convites.criar": MesaActionSpec("convites.criar", "convites.criar", "createChatInviteLink", "can_invite_users", "palco"),
}


TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    return text_value.replace("@", "").strip()[:180] or fallback


async def _telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise MesaError("token_indisponivel")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise MesaError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        description = _safe_text(data.get("description"), fallback="telegram_erro")
        raise MesaError(description)
    return data.get("result")


def _rights_from_member(member: dict[str, Any]) -> dict[str, bool]:
    status = str(member.get("status") or "").lower()
    keys = {
        "can_manage_chat",
        "can_delete_messages",
        "can_restrict_members",
        "can_invite_users",
        "can_pin_messages",
    }
    if status == "creator":
        return {key: True for key in keys}
    if status != "administrator":
        return {key: False for key in keys}
    return {key: bool(member.get(key) is True) for key in keys}


async def ensure_bot_right(
    *,
    bot_token: str,
    chat_id: int,
    required_right: str | None,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> None:
    if required_right is None:
        return
    member = await fetch_bot_member_rights(bot_token=bot_token, chat_id=chat_id, telegram_api_call=telegram_api_call)
    rights = _rights_from_member(member)
    if not rights.get(required_right, False):
        raise MesaRightError("afinação_insuficiente")


def ensure_phase5_tables(db_engine: Engine = default_engine) -> None:
    """Create action mapping and history tables used by the Mesa."""
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_alvos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    ui_ref TEXT NOT NULL UNIQUE,
                    nome_publico TEXT NOT NULL,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE (telegram_chat_id, telegram_user_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_mensagens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    ui_ref TEXT NOT NULL UNIQUE,
                    resumo_publico TEXT,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE (telegram_chat_id, telegram_message_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    historico_ref TEXT NOT NULL UNIQUE,
                    ator_ref TEXT NOT NULL,
                    palco_ref TEXT NOT NULL,
                    alvo_ref TEXT,
                    ajuste TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resumo_publico TEXT NOT NULL,
                    payload_tecnico_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_alvos_ui_ref ON eq_alvos(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_mensagens_ui_ref ON eq_mensagens(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_historico_palco_ref ON eq_historico(palco_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_historico_created_at ON eq_historico(created_at)"))


def register_alvo_ref(
    *,
    chat_id: int,
    user_id: int,
    nome_publico: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> str:
    """Register a target user seen internally and return its public alias.

    This helper is intentionally server-side. Public APIs must receive only the
    returned ``alvo_ref``; they must not accept raw Telegram user IDs.
    """
    ensure_phase5_tables(db_engine)
    ref_seed = f"{int(chat_id)}:{int(user_id)}"
    ui_ref = make_ui_ref("usr", ref_seed, alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_alvos (telegram_chat_id, telegram_user_id, ui_ref, nome_publico, habilitado, updated_at)
                VALUES (:chat_id, :user_id, :ui_ref, :nome_publico, 1, :updated_at)
                ON CONFLICT(telegram_chat_id, telegram_user_id) DO UPDATE SET
                    ui_ref=excluded.ui_ref,
                    nome_publico=excluded.nome_publico,
                    habilitado=1,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
                "ui_ref": ui_ref,
                "nome_publico": _safe_text(nome_publico, fallback="Membro"),
                "updated_at": _now_iso(),
            },
        )
    return ui_ref


def register_mensagem_ref(
    *,
    chat_id: int,
    message_id: int,
    resumo_publico: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> str:
    """Register a message seen internally and return its public alias."""
    ensure_phase5_tables(db_engine)
    ref_seed = f"{int(chat_id)}:{int(message_id)}"
    ui_ref = "msg_" + make_ui_ref("grp", ref_seed, alias_secret).split("_", 1)[1]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_mensagens (telegram_chat_id, telegram_message_id, ui_ref, resumo_publico, habilitado, updated_at)
                VALUES (:chat_id, :message_id, :ui_ref, :resumo_publico, 1, :updated_at)
                ON CONFLICT(telegram_chat_id, telegram_message_id) DO UPDATE SET
                    ui_ref=excluded.ui_ref,
                    resumo_publico=excluded.resumo_publico,
                    habilitado=1,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "ui_ref": ui_ref,
                "resumo_publico": _safe_text(resumo_publico, fallback="Mensagem"),
                "updated_at": _now_iso(),
            },
        )
    return ui_ref


def resolve_alvo_ref(*, palco_id: int, alvo_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_user_id, ui_ref, nome_publico
                FROM eq_alvos
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref AND habilitado=1
                """
            ),
            {"chat_id": int(palco_id), "ui_ref": str(alvo_ref)},
        ).mappings().first()
    if not row:
        raise MesaNotFoundError("alvo_indisponivel")
    return dict(row)


def resolve_mensagem_ref(*, palco_id: int, msg_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_message_id, ui_ref, resumo_publico
                FROM eq_mensagens
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref AND habilitado=1
                """
            ),
            {"chat_id": int(palco_id), "ui_ref": str(msg_ref)},
        ).mappings().first()
    if not row:
        raise MesaNotFoundError("mensagem_indisponivel")
    return dict(row)


def _history_ref(*, ator_ref: str, palco_ref: str, ajuste: str, created_at: str, alias_secret: str) -> str:
    seed = f"{ator_ref}:{palco_ref}:{ajuste}:{created_at}"
    return "his_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def record_historico(
    *,
    ator_ref: str,
    palco_ref: str,
    alvo_ref: str | None,
    ajuste: str,
    status: str,
    resumo_publico: str,
    payload_tecnico: dict[str, Any] | None,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    created_at = _now_iso()
    historico_ref = _history_ref(ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste, created_at=created_at, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_historico (
                    historico_ref, ator_ref, palco_ref, alvo_ref, ajuste, status, resumo_publico,
                    payload_tecnico_json, created_at
                ) VALUES (
                    :historico_ref, :ator_ref, :palco_ref, :alvo_ref, :ajuste, :status, :resumo_publico,
                    :payload_tecnico_json, :created_at
                )
                """
            ),
            {
                "historico_ref": historico_ref,
                "ator_ref": ator_ref,
                "palco_ref": palco_ref,
                "alvo_ref": alvo_ref,
                "ajuste": ajuste,
                "status": status,
                "resumo_publico": _safe_text(resumo_publico, fallback="Ajuste registrado"),
                "payload_tecnico_json": json.dumps(payload_tecnico or {}, ensure_ascii=False, sort_keys=True),
                "created_at": created_at,
            },
        )
    return {
        "historico_ref": historico_ref,
        "ajuste": ajuste,
        "status": status,
        "resumo": _safe_text(resumo_publico, fallback="Ajuste registrado"),
        "created_at": created_at,
    }


def list_historico_publico(
    *,
    palco_refs: set[str],
    limit: int = 50,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    ensure_phase5_tables(db_engine)
    if not palco_refs:
        return []
    safe_limit = max(1, min(int(limit), 100))
    placeholders = ", ".join(f":palco_{idx}" for idx, _ in enumerate(palco_refs))
    params: dict[str, object] = {f"palco_{idx}": ref for idx, ref in enumerate(palco_refs)}
    params["limit"] = safe_limit
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT historico_ref, ator_ref, palco_ref, alvo_ref, ajuste, status, resumo_publico, created_at
                FROM eq_historico
                WHERE palco_ref IN ({placeholders})
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [
        {
            "historico_ref": str(row["historico_ref"]),
            "ator_ref": str(row["ator_ref"]),
            "palco_ref": str(row["palco_ref"]),
            "alvo_ref": row["alvo_ref"],
            "ajuste": str(row["ajuste"]),
            "status": str(row["status"]),
            "resumo": str(row["resumo_publico"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _silenciar_permissions() -> dict[str, bool]:
    return {
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
        "can_manage_topics": False,
    }


def _liberar_permissions() -> dict[str, bool]:
    return {
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_change_info": True,
        "can_invite_users": True,
        "can_pin_messages": True,
        "can_manage_topics": True,
    }


def build_action_payload(
    *,
    ajuste: str,
    palco_id: int,
    payload: dict[str, Any],
    db_engine: Engine = default_engine,
) -> tuple[dict[str, Any], str | None, str]:
    """Build the Bot API payload from public refs only."""
    if ajuste not in ACTION_SPECS:
        raise MesaError("ajuste_indisponivel")

    if ajuste in {"mensagens.apagar", "fixados.criar", "fixados.remover"}:
        msg_ref = _safe_text(payload.get("msg_ref"))
        if not msg_ref.startswith("msg_"):
            raise MesaNotFoundError("mensagem_indisponivel")
        message = resolve_mensagem_ref(palco_id=palco_id, msg_ref=msg_ref, db_engine=db_engine)
        telegram_payload: dict[str, Any] = {
            "chat_id": int(palco_id),
            "message_id": int(message["telegram_message_id"]),
        }
        if ajuste == "fixados.criar":
            telegram_payload["disable_notification"] = bool(payload.get("sem_notificacao", True))
        return telegram_payload, str(message["ui_ref"]), str(message.get("resumo_publico") or "Mensagem")

    if ajuste in {"membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar"}:
        alvo_ref = _safe_text(payload.get("alvo_ref"))
        if not alvo_ref.startswith("usr_"):
            raise MesaNotFoundError("alvo_indisponivel")
        target = resolve_alvo_ref(palco_id=palco_id, alvo_ref=alvo_ref, db_engine=db_engine)
        telegram_payload = {"chat_id": int(palco_id), "user_id": int(target["telegram_user_id"])}
        if ajuste == "membros.silenciar":
            duration = int(payload.get("duracao_segundos") or 3600)
            until_date = _now_unix() + max(60, min(duration, 366 * 24 * 60 * 60))
            telegram_payload.update(
                {
                    "permissions": _silenciar_permissions(),
                    "use_independent_chat_permissions": True,
                    "until_date": until_date,
                }
            )
        elif ajuste == "membros.liberar":
            telegram_payload.update(
                {
                    "permissions": _liberar_permissions(),
                    "use_independent_chat_permissions": True,
                }
            )
        elif ajuste == "membros.remover":
            telegram_payload["revoke_messages"] = bool(payload.get("revogar_mensagens", False))
        elif ajuste == "membros.reintegrar":
            telegram_payload["only_if_banned"] = bool(payload.get("apenas_se_banido", True))
        return telegram_payload, str(target["ui_ref"]), str(target.get("nome_publico") or "Membro")

    if ajuste == "convites.criar":
        name = _safe_text(payload.get("nome"), fallback="Equalizador")[:32]
        telegram_payload = {"chat_id": int(palco_id), "name": name}
        expire_seconds = int(payload.get("expira_em_segundos") or 0)
        if expire_seconds > 0:
            telegram_payload["expire_date"] = _now_unix() + min(expire_seconds, 30 * 24 * 60 * 60)
        member_limit = int(payload.get("limite_membros") or 0)
        if member_limit > 0:
            telegram_payload["member_limit"] = max(1, min(member_limit, 99999))
        if bool(payload.get("solicitar_aprovacao", False)):
            telegram_payload.pop("member_limit", None)
            telegram_payload["creates_join_request"] = True
        return telegram_payload, None, "Convite"

    raise MesaError("ajuste_indisponivel")


async def executar_ajuste(
    *,
    ajuste: str,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Execute a light moderation adjustment and record sanitized history."""
    spec = ACTION_SPECS.get(ajuste)
    if not spec:
        raise MesaError("ajuste_indisponivel")
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload, alvo_ref, alvo_label = build_action_payload(
        ajuste=ajuste,
        palco_id=palco_id,
        payload=payload,
        db_engine=db_engine,
    )

    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right=spec.direito,
            telegram_api_call=telegram_api_call,
        )
        result = await telegram_api_call(bot_token, spec.telegram_method, telegram_payload)
        invite_link = None
        if ajuste == "convites.criar" and isinstance(result, dict):
            invite_link = str(result.get("invite_link") or "") or None
        resumo = f"{spec.ajuste} concluído em {palco.get('titulo') or 'Palco'}"
        if alvo_label:
            resumo = f"{spec.ajuste} concluído: {alvo_label}"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="concluido",
            resumo_publico=resumo,
            payload_tecnico={"method": spec.telegram_method, "payload": telegram_payload},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        response: dict[str, object] = {
            "ok": True,
            "ajuste": spec.ajuste,
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
        }
        if invite_link:
            response["convite"] = invite_link
        return response
    except Exception as exc:
        resumo = f"{spec.ajuste} não concluído"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="falhou",
            resumo_publico=resumo,
            payload_tecnico={"erro": _safe_text(exc, fallback=exc.__class__.__name__), "method": spec.telegram_method},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MesaRightError):
            raise
        if isinstance(exc, MesaNotFoundError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MesaError("ajuste_falhou") from exc


def list_mensagens_publicas(
    *,
    palco_id: int,
    limit: int = 25,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Return recent message aliases for the Mesa UI without exposing message_id."""
    ensure_phase5_tables(db_engine)
    safe_limit = max(1, min(int(limit), 50))
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ui_ref, resumo_publico, updated_at
                FROM eq_mensagens
                WHERE telegram_chat_id=:chat_id AND habilitado=1
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"chat_id": int(palco_id), "limit": safe_limit},
        ).mappings().all()
    return [
        {
            "msg_ref": str(row["ui_ref"]),
            "resumo": str(row["resumo_publico"] or "Mensagem"),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def list_alvos_publicos(
    *,
    palco_id: int,
    limit: int = 25,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Return recent member aliases for the Mesa UI without exposing user_id."""
    ensure_phase5_tables(db_engine)
    safe_limit = max(1, min(int(limit), 50))
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ui_ref, nome_publico, updated_at
                FROM eq_alvos
                WHERE telegram_chat_id=:chat_id AND habilitado=1
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"chat_id": int(palco_id), "limit": safe_limit},
        ).mappings().all()
    return [
        {
            "alvo_ref": str(row["ui_ref"]),
            "nome": str(row["nome_publico"] or "Membro"),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]
