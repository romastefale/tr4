from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
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


def maestro_error_public_detail(exc: BaseException) -> str:
    """Return a sanitized operator-facing detail for Maestro failures."""
    if isinstance(exc, MaestroConfirmationError):
        return "Confirmação exigida."
    reason = _safe_text(exc, fallback="maestro_erro")
    known = {
        "transmissao_vazia": "Escreva o texto da transmissão.",
        "transmissao_longa": "Transmissão acima do limite do Telegram.",
        "modo_silencio_falhou": "Modo silêncio não concluído.",
        "modo_silencio_desativar_falhou": "Desativação do modo silêncio não concluída.",
        "transmissao_falhou": "Transmissão não concluída.",
        "maestro_erro": "Ajuste crítico não concluído.",
    }
    return known.get(reason, "Ajuste crítico não concluído.")


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


def _silencio_liberado_permissions() -> dict[str, bool]:
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
        "can_change_info": False,
        "can_invite_users": True,
        "can_pin_messages": False,
        "can_manage_topics": True,
    }


def _clean_permissions(raw: object) -> dict[str, bool]:
    allowed = set(_silencio_permissions())
    if not isinstance(raw, dict):
        return _silencio_liberado_permissions()
    cleaned: dict[str, bool] = {}
    for key in allowed:
        value = raw.get(key)
        if value is not None:
            cleaned[key] = bool(value is True)
    return cleaned or _silencio_liberado_permissions()


def ensure_maestro_tables(db_engine: Engine = default_engine) -> None:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_silencio_estado (
                    palco_ref TEXT PRIMARY KEY,
                    previous_permissions_json TEXT,
                    ativo INTEGER NOT NULL DEFAULT 0,
                    ator_ref TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )


def _store_silencio_estado(*, palco_ref: str, previous_permissions: dict[str, bool], ator_ref: str, ativo: bool, db_engine: Engine) -> None:
    ensure_maestro_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_silencio_estado (palco_ref, previous_permissions_json, ativo, ator_ref, updated_at)
                VALUES (:palco_ref, :previous_permissions_json, :ativo, :ator_ref, :updated_at)
                ON CONFLICT(palco_ref) DO UPDATE SET
                    previous_permissions_json = excluded.previous_permissions_json,
                    ativo = excluded.ativo,
                    ator_ref = excluded.ator_ref,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "palco_ref": palco_ref,
                "previous_permissions_json": json.dumps(previous_permissions, ensure_ascii=False),
                "ativo": 1 if ativo else 0,
                "ator_ref": ator_ref,
                "updated_at": _now_iso(),
            },
        )


def _load_silencio_permissions(*, palco_ref: str, db_engine: Engine) -> tuple[dict[str, bool], bool]:
    ensure_maestro_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT previous_permissions_json
                FROM eq_silencio_estado
                WHERE palco_ref = :palco_ref AND ativo = 1
                """
            ),
            {"palco_ref": palco_ref},
        ).mappings().first()
    if not row:
        return _silencio_liberado_permissions(), True
    try:
        raw = json.loads(str(row.get("previous_permissions_json") or "{}"))
    except json.JSONDecodeError:
        raw = {}
    return _clean_permissions(raw), False


def _mark_silencio_inativo(*, palco_ref: str, db_engine: Engine) -> None:
    ensure_maestro_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_silencio_estado
                SET ativo = 0, updated_at = :updated_at
                WHERE palco_ref = :palco_ref
                """
            ),
            {"palco_ref": palco_ref, "updated_at": _now_iso()},
        )


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


def build_silencio_desativar_payload(*, palco_id: int, payload: dict[str, Any], palco_ref: str, db_engine: Engine) -> tuple[dict[str, Any], bool]:
    require_maestro_confirmation(payload)
    permissions, usado_fallback = _load_silencio_permissions(palco_ref=palco_ref, db_engine=db_engine)
    return {
        "chat_id": int(palco_id),
        "permissions": permissions,
        "use_independent_chat_permissions": True,
    }, usado_fallback


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
        chat_info = await telegram_api_call(bot_token, "getChat", {"chat_id": palco_id})
        previous_permissions = _clean_permissions(chat_info.get("permissions") if isinstance(chat_info, dict) else {})
        _store_silencio_estado(
            palco_ref=palco_ref,
            previous_permissions=previous_permissions,
            ator_ref=ator_ref,
            ativo=True,
            db_engine=db_engine,
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
            resumo_publico=f"Modo silêncio não concluído · {maestro_error_public_detail(exc) if isinstance(exc, MaestroError) else _safe_text(exc, fallback='Telegram recusou a operação')}",
            payload_tecnico={"erro": _safe_text(exc, fallback=exc.__class__.__name__), "method": "setChatPermissions"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MaestroError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MaestroError("modo_silencio_falhou") from exc


async def executar_modo_silencio_desativar(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Restore non-administrator chat permissions saved before modo silêncio."""
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload, usado_fallback = build_silencio_desativar_payload(
        palco_id=palco_id, payload=payload, palco_ref=palco_ref, db_engine=db_engine
    )
    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right="can_restrict_members",
            telegram_api_call=telegram_api_call,
        )
        await telegram_api_call(bot_token, "setChatPermissions", telegram_payload)
        _mark_silencio_inativo(palco_ref=palco_ref, db_engine=db_engine)
        resumo = f"Modo silêncio desativado em {palco.get('titulo') or 'Palco'}"
        if usado_fallback:
            resumo += " · permissões amplas aplicadas por ausência de estado anterior"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="silencio.desativar",
            status="concluido",
            resumo_publico=resumo,
            payload_tecnico={"method": "setChatPermissions", "fallback": usado_fallback},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {
            "ok": True,
            "ajuste": "silencio.desativar",
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
            "fallback": usado_fallback,
        }
    except Exception as exc:
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="silencio.desativar",
            status="falhou",
            resumo_publico=f"Desativação do modo silêncio não concluída · {_safe_text(exc, fallback='Telegram recusou a operação')}",
            payload_tecnico={"erro": _safe_text(exc, fallback=exc.__class__.__name__), "method": "setChatPermissions"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MaestroError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MaestroError("modo_silencio_desativar_falhou") from exc


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
        message_id: int | None = None
        if isinstance(result, dict) and result.get("message_id") is not None:
            message_id = int(result["message_id"])
            msg_ref = register_mensagem_ref(
                chat_id=palco_id,
                message_id=message_id,
                resumo_publico="Transmissão",
                alias_secret=alias_secret,
                db_engine=db_engine,
            )
        fixacao: dict[str, object] | None = None
        if bool(payload.get("fixar")) and message_id is not None:
            try:
                await ensure_bot_right(
                    bot_token=bot_token,
                    chat_id=palco_id,
                    required_right="can_pin_messages",
                    telegram_api_call=telegram_api_call,
                )
                await telegram_api_call(
                    bot_token,
                    "pinChatMessage",
                    {"chat_id": palco_id, "message_id": message_id, "disable_notification": True},
                )
                fixacao = {"ok": True}
            except MesaError as exc:
                fixacao = {"ok": False, "motivo": mesa_error_public_detail(exc)}
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=msg_ref,
            ajuste="transmissao.enviar",
            status="concluido",
            resumo_publico=f"Transmissão enviada em {palco.get('titulo') or 'Palco'}",
            payload_tecnico={"method": "sendMessage", "payload": telegram_payload, "fixacao": fixacao},
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
        if fixacao is not None:
            response["fixacao"] = fixacao
        return response
    except Exception as exc:
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="transmissao.enviar",
            status="falhou",
            resumo_publico=f"Transmissão não concluída · {maestro_error_public_detail(exc) if isinstance(exc, MaestroError) else _safe_text(exc, fallback='Telegram recusou a operação')}",
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
    payload = {
        "exportacao_ref": export_ref,
        "gerado_em": generated_at,
        "formato": "json",
        "total_registros": len(rows),
        "registros": rows,
    }
    payload["json_texto"] = json.dumps(payload, ensure_ascii=False, indent=2)
    return payload


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
