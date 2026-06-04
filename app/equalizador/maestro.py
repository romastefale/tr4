from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import (
    MesaError,
    TelegramApiCallable,
    _telegram_api_call,
    ensure_bot_right,
    ensure_phase5_tables,
    list_historico_publico,
    record_historico,
    register_mensagem_ref,
)
from app.equalizador.palcos import list_equalizador_palcos
from app.equalizador.permissions import parse_equalizador_canais

MAESTRO_CONFIRMATION_PHRASE = "CONFIRMAR AJUSTE"


class MaestroError(RuntimeError):
    """Raised when a critical Maestro action cannot be executed."""


class MaestroConfirmationError(MaestroError):
    """Raised when a critical action lacks the required confirmation phrase."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    return text_value.replace("@", "").strip()[:300] or fallback


def require_maestro_confirmation(payload: dict[str, Any]) -> None:
    """Require an explicit confirmation phrase for critical Maestro actions."""
    confirmation = str(payload.get("confirmacao") or "").strip().upper()
    if confirmation != MAESTRO_CONFIRMATION_PHRASE:
        raise MaestroConfirmationError("confirmacao_exigida")


def _silencio_permissions() -> dict[str, bool]:
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


def build_silencio_payload(*, palco_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    require_maestro_confirmation(payload)
    return {
        "chat_id": int(palco_id),
        "permissions": _silencio_permissions(),
        "use_independent_chat_permissions": True,
    }


def build_transmissao_payload(*, palco_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    require_maestro_confirmation(payload)
    text = str(payload.get("texto") or "").strip()
    if not text:
        raise MaestroError("transmissao_vazia")
    if len(text) > 4096:
        raise MaestroError("transmissao_longa")
    return {
        "chat_id": int(palco_id),
        "text": text,
        "disable_web_page_preview": bool(payload.get("sem_preview", True)),
        "disable_notification": bool(payload.get("sem_notificacao", False)),
    }


async def executar_modo_silencio(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Activate group-wide silent mode through Telegram setChatPermissions."""
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload = build_silencio_payload(palco_id=palco_id, payload=payload)
    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right="can_restrict_members",
            telegram_api_call=telegram_api_call,
        )
        await telegram_api_call(bot_token, "setChatPermissions", telegram_payload)
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="silencio.ativar",
            status="concluido",
            resumo_publico=f"Modo silêncio ativado em {palco.get('titulo') or 'Palco'}",
            payload_tecnico={"method": "setChatPermissions", "payload": telegram_payload},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {
            "ok": True,
            "ajuste": "silencio.ativar",
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
        }
    except Exception as exc:
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="silencio.ativar",
            status="falhou",
            resumo_publico="Modo silêncio não concluído",
            payload_tecnico={"erro": _safe_text(exc, fallback=exc.__class__.__name__), "method": "setChatPermissions"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MaestroError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MaestroError("modo_silencio_falhou") from exc


async def executar_transmissao(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Send a Maestro transmission to a palco and record sanitized history."""
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload = build_transmissao_payload(palco_id=palco_id, payload=payload)
    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right="can_manage_chat",
            telegram_api_call=telegram_api_call,
        )
        result = await telegram_api_call(bot_token, "sendMessage", telegram_payload)
        msg_ref: str | None = None
        if isinstance(result, dict) and result.get("message_id") is not None:
            msg_ref = register_mensagem_ref(
                chat_id=palco_id,
                message_id=int(result["message_id"]),
                resumo_publico="Transmissão",
                alias_secret=alias_secret,
                db_engine=db_engine,
            )
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=msg_ref,
            ajuste="transmissao.enviar",
            status="concluido",
            resumo_publico=f"Transmissão enviada em {palco.get('titulo') or 'Palco'}",
            payload_tecnico={"method": "sendMessage", "payload": telegram_payload},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        response: dict[str, object] = {
            "ok": True,
            "ajuste": "transmissao.enviar",
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
        }
        if msg_ref:
            response["msg_ref"] = msg_ref
        return response
    except Exception as exc:
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="transmissao.enviar",
            status="falhou",
            resumo_publico="Transmissão não concluída",
            payload_tecnico={"erro": _safe_text(exc, fallback=exc.__class__.__name__), "method": "sendMessage"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MaestroError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MaestroError("transmissao_falhou") from exc


def exportar_historico_publico(
    *,
    palco_refs: set[str],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    """Return a sanitized history export; technical payloads stay hidden."""
    ensure_phase5_tables(db_engine)
    generated_at = _now_iso()
    rows = list_historico_publico(palco_refs=palco_refs, limit=100, db_engine=db_engine)
    export_ref = "exp_" + make_ui_ref("grp", f"historico:{generated_at}:{len(rows)}", alias_secret).split("_", 1)[1]
    return {
        "exportacao_ref": export_ref,
        "gerado_em": generated_at,
        "formato": "json",
        "registros": rows,
    }


def distribuicao_canais_publica(
    *,
    raw_canais: str,
    allowed_palco_ids: set[int],
    visible_palco_ids: set[int],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Render TR4_EQUALIZADOR_CANAIS without numeric Telegram identifiers."""
    grants = parse_equalizador_canais(raw_canais)
    if not grants or not visible_palco_ids:
        return []

    palcos = list_equalizador_palcos(palco_ids=allowed_palco_ids, alias_secret=alias_secret, db_engine=db_engine)
    palco_by_ref: dict[str, dict[str, object]] = {str(palco["grp_ref"]): palco for palco in palcos}
    palco_ref_by_id = {int(chat_id): make_ui_ref("grp", int(chat_id), alias_secret) for chat_id in allowed_palco_ids}

    rows: list[dict[str, object]] = []
    for grant in grants:
        if grant.chat_id is not None and int(grant.chat_id) not in visible_palco_ids:
            continue
        if grant.chat_id is None:
            palco_payload: dict[str, object] = {"escopo": "todos os palcos configurados"}
        else:
            palco_ref = palco_ref_by_id.get(int(grant.chat_id), make_ui_ref("grp", int(grant.chat_id), alias_secret))
            palco_row = palco_by_ref.get(palco_ref, {})
            palco_payload = {
                "grp_ref": palco_ref,
                "titulo": str(palco_row.get("titulo") or "Palco sem título"),
            }
        operador_payload: dict[str, object]
        if grant.user_id is None:
            operador_payload = {"escopo": "todos os operadores autorizados"}
        else:
            operador_payload = {"usr_ref": make_ui_ref("usr", int(grant.user_id), alias_secret)}
        canais = ["*"] if grant.todos_canais else sorted(grant.canais)
        rows.append({"operador": operador_payload, "palco": palco_payload, "canais": canais})
    return rows
