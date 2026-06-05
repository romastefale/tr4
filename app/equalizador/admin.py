from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.equalizador.maestro import MAESTRO_CONFIRMATION_PHRASE
from app.equalizador.mesa import (
    MesaError,
    MesaRightError,
    MesaTargetError,
    MesaTelegramError,
    _safe_error_text,
    _safe_text,
    ensure_phase5_tables,
    record_historico,
    resolve_alvo_ref,
)

TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


class AdminCriticoError(MesaError):
    """Raised when an extreme administrative action cannot be executed."""


class AdminConfirmationError(AdminCriticoError):
    """Raised when the required double confirmation is missing."""


@dataclass(frozen=True)
class AdminActionSpec:
    ajuste: str
    canal_codigo: str
    telegram_method: str
    direito: str
    target_kind: str


ADMIN_SPECS: dict[str, AdminActionSpec] = {
    "grupo.titulo": AdminActionSpec("grupo.titulo", "grupo.titulo", "setChatTitle", "can_change_info", "palco"),
    "grupo.descricao": AdminActionSpec("grupo.descricao", "grupo.descricao", "setChatDescription", "can_change_info", "palco"),
    "admins.promover": AdminActionSpec("admins.promover", "admins.promover", "promoteChatMember", "can_promote_members", "alvo"),
    "admins.rebaixar": AdminActionSpec("admins.rebaixar", "admins.rebaixar", "promoteChatMember", "can_promote_members", "alvo"),
    "admins.titulo": AdminActionSpec("admins.titulo", "admins.titulo", "setChatAdministratorCustomTitle", "can_promote_members", "alvo"),
}

_ADMIN_PROMOTE_FLAGS: tuple[str, ...] = (
    "can_manage_chat",
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
    "can_pin_messages",
    "can_manage_topics",
    "can_manage_video_chats",
    "can_promote_members",
)


async def telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise AdminCriticoError("Token do bot indisponível.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise AdminCriticoError("Telegram retornou resposta inválida.") from exc
    if not response.is_success or data.get("ok") is not True:
        raise MesaTelegramError(str(data.get("description") or "telegram_erro"))
    return data.get("result")


def admin_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, AdminConfirmationError):
        return "Confirmação crítica exigida."
    if isinstance(exc, MesaTelegramError):
        return f"Telegram recusou: {_safe_error_text(exc.description, fallback='operação recusada')}"
    if isinstance(exc, MesaRightError):
        return "Afinação insuficiente."
    if isinstance(exc, MesaTargetError):
        return _safe_error_text(exc.description, fallback="Alvo indisponível.")
    return _safe_error_text(exc, fallback="Administração crítica indisponível.")


def require_extreme_confirmation(payload: dict[str, Any]) -> None:
    phrase = str(payload.get("confirmacao") or "").strip().upper()
    if phrase != MAESTRO_CONFIRMATION_PHRASE:
        raise AdminConfirmationError("confirmacao_exigida")
    acknowledged = bool(payload.get("ciente") is True)
    if not acknowledged:
        raise AdminConfirmationError("ciencia_exigida")


def _rights_from_member(member: dict[str, Any]) -> dict[str, bool]:
    status = str(member.get("status") or "").lower()
    keys = set(_ADMIN_PROMOTE_FLAGS) | {"can_change_info"}
    if status == "creator":
        return {key: True for key in keys}
    if status != "administrator":
        return {key: False for key in keys}
    return {key: bool(member.get(key) is True) for key in keys}


async def ensure_admin_right(
    *,
    bot_token: str,
    chat_id: int,
    required_right: str,
    telegram_api_call_fn: TelegramApiCallable = telegram_api_call,
) -> None:
    me = await telegram_api_call_fn(bot_token, "getMe", None)
    bot_id = int((me or {}).get("id") or 0)
    if bot_id <= 0:
        raise AdminCriticoError("Bot indisponível.")
    member = await telegram_api_call_fn(bot_token, "getChatMember", {"chat_id": int(chat_id), "user_id": bot_id})
    if not isinstance(member, dict):
        raise AdminCriticoError("Afinação indisponível.")
    rights = _rights_from_member(member)
    if not rights.get(required_right, False):
        raise MesaRightError("afinação_insuficiente")


def _safe_title(payload: dict[str, Any]) -> str:
    title = _safe_text(payload.get("titulo"), fallback="")[:128]
    if not title:
        raise AdminCriticoError("Informe o título do palco.")
    return title


def _safe_description(payload: dict[str, Any]) -> str:
    return _safe_text(payload.get("descricao"), fallback="")[:255]


def _safe_admin_title(payload: dict[str, Any]) -> str:
    title = _safe_text(payload.get("titulo_admin"), fallback="")[:16]
    if not title:
        raise AdminCriticoError("Informe o título do administrador.")
    return title


def _promote_payload(*, chat_id: int, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"chat_id": int(chat_id), "user_id": int(user_id)}
    direitos = payload.get("direitos")
    if isinstance(direitos, dict):
        for flag in _ADMIN_PROMOTE_FLAGS:
            data[flag] = bool(direitos.get(flag) is True)
    else:
        perfil = str(payload.get("perfil") or "moderador").strip().lower()
        can_manage_topics = perfil in {"moderador", "maestro"}
        data.update({
            "can_manage_chat": True,
            "can_delete_messages": True,
            "can_restrict_members": True,
            "can_invite_users": True,
            "can_pin_messages": True,
            "can_manage_topics": can_manage_topics,
            "can_manage_video_chats": False,
            "can_promote_members": perfil == "maestro",
        })
    return data


def _demote_payload(*, chat_id: int, user_id: int) -> dict[str, Any]:
    data: dict[str, Any] = {"chat_id": int(chat_id), "user_id": int(user_id)}
    for flag in _ADMIN_PROMOTE_FLAGS:
        data[flag] = False
    return data


def build_admin_payload(
    *,
    ajuste: str,
    palco_id: int,
    payload: dict[str, Any],
    db_engine: Any,
) -> tuple[dict[str, Any], str | None, str]:
    require_extreme_confirmation(payload)
    if ajuste == "grupo.titulo":
        title = _safe_title(payload)
        return {"chat_id": int(palco_id), "title": title}, None, title
    if ajuste == "grupo.descricao":
        description = _safe_description(payload)
        return {"chat_id": int(palco_id), "description": description}, None, "Descrição atualizada" if description else "Descrição removida"

    alvo_ref = _safe_text(payload.get("alvo_ref"), fallback="")
    if not alvo_ref:
        raise MesaTargetError("Escolha um membro registrado.")
    alvo = resolve_alvo_ref(palco_id=int(palco_id), alvo_ref=alvo_ref, db_engine=db_engine)
    user_id = int(alvo["telegram_user_id"])
    nome = _safe_text(alvo.get("nome_publico"), fallback="Membro")

    if ajuste == "admins.promover":
        return _promote_payload(chat_id=int(palco_id), user_id=user_id, payload=payload), alvo_ref, f"Promover · {nome}"
    if ajuste == "admins.rebaixar":
        return _demote_payload(chat_id=int(palco_id), user_id=user_id), alvo_ref, f"Rebaixar · {nome}"
    if ajuste == "admins.titulo":
        title = _safe_admin_title(payload)
        return {"chat_id": int(palco_id), "user_id": user_id, "custom_title": title}, alvo_ref, f"Título admin · {nome}"
    raise AdminCriticoError("Ação crítica indisponível.")


async def executar_admin_critico(
    *,
    ajuste: str,
    palco: dict[str, Any],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Any,
    telegram_api_call_fn: TelegramApiCallable = telegram_api_call,
) -> dict[str, object]:
    spec = ADMIN_SPECS.get(ajuste)
    if not spec:
        raise AdminCriticoError("Ação crítica indisponível.")
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    await ensure_admin_right(bot_token=bot_token, chat_id=palco_id, required_right=spec.direito, telegram_api_call_fn=telegram_api_call_fn)
    api_payload, alvo_ref, label = build_admin_payload(ajuste=ajuste, palco_id=palco_id, payload=payload, db_engine=db_engine)
    await telegram_api_call_fn(bot_token, spec.telegram_method, api_payload)
    historico = record_historico(
        ator_ref=ator_ref,
        palco_ref=palco_ref,
        alvo_ref=alvo_ref,
        ajuste=ajuste,
        status="ok",
        resumo_publico=f"{label} concluído.",
        payload_tecnico={"telegram_method": spec.telegram_method, "target_kind": spec.target_kind},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {
        "resultado": {"ajuste": ajuste, "estado": "concluido", "nome": label},
        "historico": historico,
        "resumo": f"{label} concluído.",
    }
