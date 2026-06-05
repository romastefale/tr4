
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import (
    MesaError,
    MesaNotFoundError,
    MesaRightError,
    MesaTargetError,
    MesaTelegramError,
    _safe_error_text,
    _safe_int,
    _safe_text,
    ensure_bot_right,
    ensure_phase5_tables,
    record_historico,
    resolve_alvo_ref,
    resolve_mensagem_ref,
)

TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


class AvancadoError(MesaError):
    """Raised when an advanced moderation action cannot be executed."""


@dataclass(frozen=True)
class AdvancedSpec:
    ajuste: str
    canal_codigo: str
    telegram_method: str
    direito: str | None
    target_kind: str


ADVANCED_SPECS: dict[str, AdvancedSpec] = {
    "reacoes.mensagem.limpar": AdvancedSpec("reacoes.mensagem.limpar", "reacoes.limpar", "deleteMessageReaction", "can_delete_messages", "mensagem"),
    "reacoes.recentes.limpar": AdvancedSpec("reacoes.recentes.limpar", "reacoes.recentes.limpar", "deleteAllMessageReactions", "can_delete_messages", "alvo_ou_remetente"),
    "canais_remetentes.banir": AdvancedSpec("canais_remetentes.banir", "canais_remetentes.banir", "banChatSenderChat", "can_restrict_members", "remetente"),
    "canais_remetentes.liberar": AdvancedSpec("canais_remetentes.liberar", "canais_remetentes.liberar", "unbanChatSenderChat", "can_restrict_members", "remetente"),
    "membros.tag.definir": AdvancedSpec("membros.tag.definir", "membros.tag.definir", "setChatMemberTag", "can_manage_tags", "alvo"),
    "topicos.criar": AdvancedSpec("topicos.criar", "topicos.criar", "createForumTopic", "can_manage_topics", "topico"),
    "topicos.editar": AdvancedSpec("topicos.editar", "topicos.editar", "editForumTopic", "can_manage_topics", "topico"),
    "topicos.fechar": AdvancedSpec("topicos.fechar", "topicos.fechar", "closeForumTopic", "can_manage_topics", "topico"),
    "topicos.reabrir": AdvancedSpec("topicos.reabrir", "topicos.reabrir", "reopenForumTopic", "can_manage_topics", "topico"),
    "topicos.apagar": AdvancedSpec("topicos.apagar", "topicos.apagar", "deleteForumTopic", "can_delete_messages", "topico"),
    "topicos.desfixar": AdvancedSpec("topicos.desfixar", "topicos.desfixar", "unpinAllForumTopicMessages", "can_pin_messages", "topico"),
    "topicos.geral.fechar": AdvancedSpec("topicos.geral.fechar", "topicos.geral.fechar", "closeGeneralForumTopic", "can_manage_topics", "palco"),
    "topicos.geral.reabrir": AdvancedSpec("topicos.geral.reabrir", "topicos.geral.reabrir", "reopenGeneralForumTopic", "can_manage_topics", "palco"),
    "topicos.geral.ocultar": AdvancedSpec("topicos.geral.ocultar", "topicos.geral.ocultar", "hideGeneralForumTopic", "can_manage_topics", "palco"),
    "topicos.geral.exibir": AdvancedSpec("topicos.geral.exibir", "topicos.geral.exibir", "unhideGeneralForumTopic", "can_manage_topics", "palco"),
    "topicos.geral.desfixar": AdvancedSpec("topicos.geral.desfixar", "topicos.geral.desfixar", "unpinAllGeneralForumTopicMessages", "can_pin_messages", "palco"),
}


async def telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise AvancadoError("Token do bot indisponível.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise AvancadoError("Telegram retornou resposta inválida.") from exc
    if not response.is_success or data.get("ok") is not True:
        raise MesaTelegramError(str(data.get("description") or "telegram_erro"))
    return data.get("result")


def avancado_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, MesaTelegramError):
        return f"Telegram recusou: {_safe_error_text(exc.description, fallback='operação recusada')}"
    if isinstance(exc, MesaRightError):
        return "Afinação insuficiente."
    if isinstance(exc, MesaNotFoundError):
        return "Referência indisponível."
    if isinstance(exc, MesaTargetError):
        return _safe_error_text(exc.description if hasattr(exc, 'description') else str(exc), fallback="Alvo indisponível.")
    return _safe_error_text(exc, fallback="Ajuste avançado indisponível.")


def _now_text() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def ensure_phase44_tables(db_engine: Engine = default_engine) -> None:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_sender_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id INTEGER NOT NULL,
                sender_chat_id INTEGER NOT NULL,
                sender_ref TEXT NOT NULL UNIQUE,
                titulo_publico TEXT NOT NULL,
                username TEXT,
                habilitado INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                UNIQUE (telegram_chat_id, sender_chat_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_topicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                topico_ref TEXT NOT NULL UNIQUE,
                nome_publico TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'aberto',
                updated_at TEXT NOT NULL,
                UNIQUE (telegram_chat_id, message_thread_id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_sender_chats_chat ON eq_sender_chats(telegram_chat_id, habilitado)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_topicos_chat ON eq_topicos(telegram_chat_id, estado)"))


def register_sender_chat_ref(*, chat_id: int, sender_chat_id: int, titulo_publico: str, alias_secret: str, username: str | None = None, db_engine: Engine = default_engine) -> str:
    ensure_phase44_tables(db_engine)
    ref = "snd_" + make_ui_ref("grp", f"{int(chat_id)}:{int(sender_chat_id)}", alias_secret).split("_", 1)[1]
    with db_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO eq_sender_chats (telegram_chat_id, sender_chat_id, sender_ref, titulo_publico, username, habilitado, updated_at)
            VALUES (:chat_id, :sender_chat_id, :sender_ref, :titulo_publico, :username, 1, :updated_at)
            ON CONFLICT(telegram_chat_id, sender_chat_id) DO UPDATE SET
                sender_ref=excluded.sender_ref,
                titulo_publico=excluded.titulo_publico,
                username=COALESCE(excluded.username, eq_sender_chats.username),
                habilitado=1,
                updated_at=excluded.updated_at
        """), {
            "chat_id": int(chat_id),
            "sender_chat_id": int(sender_chat_id),
            "sender_ref": ref,
            "titulo_publico": _safe_text(titulo_publico, fallback="Canal remetente"),
            "username": _safe_text(username, fallback="") or None,
            "updated_at": _now_text(),
        })
    return ref


def register_topic_ref(*, chat_id: int, message_thread_id: int, nome_publico: str, alias_secret: str, estado: str = "aberto", db_engine: Engine = default_engine) -> str:
    ensure_phase44_tables(db_engine)
    ref = "top_" + make_ui_ref("grp", f"{int(chat_id)}:{int(message_thread_id)}", alias_secret).split("_", 1)[1]
    with db_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO eq_topicos (telegram_chat_id, message_thread_id, topico_ref, nome_publico, estado, updated_at)
            VALUES (:chat_id, :thread_id, :topico_ref, :nome_publico, :estado, :updated_at)
            ON CONFLICT(telegram_chat_id, message_thread_id) DO UPDATE SET
                topico_ref=excluded.topico_ref,
                nome_publico=excluded.nome_publico,
                estado=excluded.estado,
                updated_at=excluded.updated_at
        """), {
            "chat_id": int(chat_id),
            "thread_id": int(message_thread_id),
            "topico_ref": ref,
            "nome_publico": _safe_text(nome_publico, fallback=f"Tópico {int(message_thread_id)}"),
            "estado": _safe_text(estado, fallback="aberto"),
            "updated_at": _now_text(),
        })
    return ref


def list_sender_chats_publicos(*, palco_id: int, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_phase44_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT sender_ref, titulo_publico, updated_at
            FROM eq_sender_chats
            WHERE telegram_chat_id=:chat_id AND habilitado=1
            ORDER BY updated_at DESC, id DESC
            LIMIT 50
        """), {"chat_id": int(palco_id)}).mappings().all()
    return [{"sender_ref": str(row["sender_ref"]), "titulo": str(row["titulo_publico"]), "updated_at": str(row["updated_at"])} for row in rows]


def list_topics_publicos(*, palco_id: int, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_phase44_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT topico_ref, nome_publico, estado, updated_at
            FROM eq_topicos
            WHERE telegram_chat_id=:chat_id
            ORDER BY updated_at DESC, id DESC
            LIMIT 80
        """), {"chat_id": int(palco_id)}).mappings().all()
    return [{"topico_ref": str(row["topico_ref"]), "nome": str(row["nome_publico"]), "estado": str(row["estado"]), "updated_at": str(row["updated_at"])} for row in rows]


def resolve_sender_ref(*, palco_id: int, sender_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase44_tables(db_engine)
    ref = str(sender_ref or "").strip()
    if not ref.startswith("snd_"):
        raise MesaNotFoundError("remetente_indisponivel")
    with db_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT sender_chat_id, sender_ref, titulo_publico
            FROM eq_sender_chats
            WHERE telegram_chat_id=:chat_id AND sender_ref=:sender_ref AND habilitado=1
        """), {"chat_id": int(palco_id), "sender_ref": ref}).mappings().first()
    if not row:
        raise MesaNotFoundError("remetente_indisponivel")
    return dict(row)


def resolve_topic_ref(*, palco_id: int, topico_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase44_tables(db_engine)
    ref = str(topico_ref or "").strip()
    if not ref.startswith("top_"):
        raise MesaNotFoundError("topico_indisponivel")
    with db_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT message_thread_id, topico_ref, nome_publico, estado
            FROM eq_topicos
            WHERE telegram_chat_id=:chat_id AND topico_ref=:topico_ref
        """), {"chat_id": int(palco_id), "topico_ref": ref}).mappings().first()
    if not row:
        raise MesaNotFoundError("topico_indisponivel")
    return dict(row)


def _target_actor_payload(*, palco_id: int, payload: dict[str, Any], db_engine: Engine) -> tuple[dict[str, Any], str | None, str]:
    alvo_ref = _safe_text(payload.get("alvo_ref"))
    sender_ref = _safe_text(payload.get("sender_ref"))
    if alvo_ref:
        target = resolve_alvo_ref(palco_id=palco_id, alvo_ref=alvo_ref, db_engine=db_engine)
        return {"user_id": int(target["telegram_user_id"])}, str(target["ui_ref"]), str(target.get("nome_publico") or "Membro")
    if sender_ref:
        sender = resolve_sender_ref(palco_id=palco_id, sender_ref=sender_ref, db_engine=db_engine)
        return {"actor_chat_id": int(sender["sender_chat_id"])}, str(sender["sender_ref"]), str(sender.get("titulo_publico") or "Canal remetente")
    raise MesaTargetError("Escolha um membro ou canal remetente.")


def build_advanced_payload(*, ajuste: str, palco_id: int, payload: dict[str, Any], alias_secret: str, db_engine: Engine = default_engine) -> tuple[dict[str, Any], str | None, str]:
    if ajuste not in ADVANCED_SPECS:
        raise AvancadoError("Ajuste avançado indisponível.")
    if ajuste == "reacoes.mensagem.limpar":
        msg_ref = _safe_text(payload.get("msg_ref"))
        message = resolve_mensagem_ref(palco_id=palco_id, msg_ref=msg_ref, db_engine=db_engine)
        actor_payload, alvo_ref, alvo_label = _target_actor_payload(palco_id=palco_id, payload=payload, db_engine=db_engine)
        return {"chat_id": int(palco_id), "message_id": int(message["telegram_message_id"]), **actor_payload}, alvo_ref, f"Reação · {alvo_label}"
    if ajuste == "reacoes.recentes.limpar":
        actor_payload, alvo_ref, alvo_label = _target_actor_payload(palco_id=palco_id, payload=payload, db_engine=db_engine)
        return {"chat_id": int(palco_id), **actor_payload}, alvo_ref, f"Reações recentes · {alvo_label}"
    if ajuste in {"canais_remetentes.banir", "canais_remetentes.liberar"}:
        sender = resolve_sender_ref(palco_id=palco_id, sender_ref=_safe_text(payload.get("sender_ref")), db_engine=db_engine)
        return {"chat_id": int(palco_id), "sender_chat_id": int(sender["sender_chat_id"])}, str(sender["sender_ref"]), str(sender.get("titulo_publico") or "Canal remetente")
    if ajuste == "membros.tag.definir":
        alvo_ref = _safe_text(payload.get("alvo_ref"))
        target = resolve_alvo_ref(palco_id=palco_id, alvo_ref=alvo_ref, db_engine=db_engine)
        tag = _safe_text(payload.get("tag"), fallback="")[:16]
        return {"chat_id": int(palco_id), "user_id": int(target["telegram_user_id"]), "tag": tag}, str(target["ui_ref"]), str(target.get("nome_publico") or "Membro")
    if ajuste == "topicos.criar":
        name = _safe_text(payload.get("nome"), fallback="Novo tópico")[:128]
        return {"chat_id": int(palco_id), "name": name}, None, name
    if ajuste.startswith("topicos.geral."):
        return {"chat_id": int(palco_id)}, None, "Tópico Geral"
    topic = resolve_topic_ref(palco_id=palco_id, topico_ref=_safe_text(payload.get("topico_ref")), db_engine=db_engine)
    data = {"chat_id": int(palco_id), "message_thread_id": int(topic["message_thread_id"])}
    if ajuste == "topicos.editar":
        data["name"] = _safe_text(payload.get("nome"), fallback=str(topic.get("nome_publico") or "Tópico"))[:128]
    return data, str(topic["topico_ref"]), str(topic.get("nome_publico") or "Tópico")


async def executar_ajuste_avancado(
    *,
    ajuste: str,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = telegram_api_call,
) -> dict[str, object]:
    spec = ADVANCED_SPECS.get(ajuste)
    if not spec:
        raise AvancadoError("Ajuste avançado indisponível.")
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload, alvo_ref, alvo_label = build_advanced_payload(ajuste=ajuste, palco_id=palco_id, payload=payload, alias_secret=alias_secret, db_engine=db_engine)
    try:
        await ensure_bot_right(bot_token=bot_token, chat_id=palco_id, required_right=spec.direito, telegram_api_call=telegram_api_call)
        result = await telegram_api_call(bot_token, spec.telegram_method, telegram_payload)
        if ajuste == "topicos.criar" and isinstance(result, dict):
            thread_id = int(result.get("message_thread_id") or 0)
            if thread_id > 0:
                alvo_ref = register_topic_ref(chat_id=palco_id, message_thread_id=thread_id, nome_publico=str(result.get("name") or alvo_label), alias_secret=alias_secret, db_engine=db_engine)
        if ajuste in {"topicos.fechar", "topicos.geral.fechar", "topicos.geral.ocultar"} and alvo_ref:
            _set_topic_state(palco_id=palco_id, topico_ref=alvo_ref, estado="fechado", db_engine=db_engine)
        if ajuste in {"topicos.reabrir", "topicos.geral.reabrir", "topicos.geral.exibir"} and alvo_ref:
            _set_topic_state(palco_id=palco_id, topico_ref=alvo_ref, estado="aberto", db_engine=db_engine)
        if ajuste == "topicos.apagar" and alvo_ref:
            _set_topic_state(palco_id=palco_id, topico_ref=alvo_ref, estado="apagado", db_engine=db_engine)
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="concluido",
            resumo_publico=f"{spec.ajuste} concluído: {alvo_label}",
            payload_tecnico={"method": spec.telegram_method, "payload": telegram_payload},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {"ok": True, "ajuste": spec.ajuste, "status": "concluido", "historico_ref": history["historico_ref"], "resumo": history["resumo"], "alvo_ref": alvo_ref, "resultado": _public_result(spec.ajuste, alvo_label)}
    except Exception as exc:
        detail = avancado_error_public_detail(exc)
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="falhou",
            resumo_publico=f"{spec.ajuste} não concluído · {detail}",
            payload_tecnico={"erro": _safe_error_text(exc, fallback=exc.__class__.__name__), "method": spec.telegram_method},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MesaError):
            raise
        raise AvancadoError("Ajuste avançado não concluído.") from exc


def _public_result(ajuste: str, label: str) -> dict[str, object]:
    return {"nome": _safe_text(label, fallback="Referência"), "estado": ajuste.replace(".", "_")}


def _set_topic_state(*, palco_id: int, topico_ref: str, estado: str, db_engine: Engine = default_engine) -> None:
    ensure_phase44_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("""
            UPDATE eq_topicos
            SET estado=:estado, updated_at=:updated_at
            WHERE telegram_chat_id=:chat_id AND topico_ref=:topico_ref
        """), {"chat_id": int(palco_id), "topico_ref": str(topico_ref), "estado": _safe_text(estado, fallback="aberto"), "updated_at": _now_text()})
